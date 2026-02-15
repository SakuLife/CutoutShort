"""切り出しセグメント抽出機能（LLM + 規則ベース）"""
import json
import subprocess

import google.generativeai as genai

from app.config import config
from app.logging_utils import log_error, log_info, log_warning
from app.models import SegmentInfo, TranscriptSegment


class CutFinderError(Exception):
    """切り出し抽出例外"""
    pass


def pick_segments(
    transcript_json: list[TranscriptSegment],
    video_path: str,
    target_num: int = 5,
    min_sec: int = 25,
    max_sec: int = 45,
    title_hint: str | None = None,
    force_rule_based: bool = False,
    job_id: str | None = None
) -> list[SegmentInfo]:
    """
    文字起こしから切り出しセグメントを抽出

    Args:
        transcript_json: 文字起こしセグメントリスト
        video_path: 動画ファイルパス（無音検出用）
        target_num: 目標本数（3〜8）
        min_sec: 最小秒数
        max_sec: 最大秒数
        title_hint: タイトルヒント
        force_rule_based: LLMをスキップして規則ベースのみ使用
        job_id: ジョブID（ログ用）

    Returns:
        選定されたセグメントリスト

    Raises:
        CutFinderError: 抽出失敗時
    """
    log_info(
        f"Starting segment extraction (target: {target_num}, {min_sec}-{max_sec}s)",
        job_id=job_id,
        stage="cut_selecting"
    )

    try:
        # LLMベースの抽出を試行（force_rule_basedでない場合）
        if not force_rule_based and config.GEMINI_API_KEY:
            try:
                segments = _pick_segments_llm(
                    transcript_json,
                    target_num=target_num,
                    min_sec=min_sec,
                    max_sec=max_sec,
                    title_hint=title_hint,
                    job_id=job_id
                )

                if segments and len(segments) >= 3:
                    log_info(f"LLM extraction succeeded: {len(segments)} segments", job_id=job_id)
                    return segments
                else:
                    log_warning(
                        "LLM extraction returned insufficient segments, falling back to rule-based",
                        job_id=job_id,
                    )

            except Exception as e:
                log_warning(f"LLM extraction failed: {e}, falling back to rule-based", job_id=job_id)

        # 規則ベースのフォールバック
        segments = _pick_segments_rule_based(
            transcript_json,
            video_path,
            target_num=target_num,
            min_sec=min_sec,
            max_sec=max_sec,
            job_id=job_id
        )

        log_info(f"Rule-based extraction completed: {len(segments)} segments", job_id=job_id)
        return segments

    except Exception as e:
        log_error(f"Segment extraction failed: {e}", job_id=job_id, exc_info=True)
        raise CutFinderError(f"Segment extraction error: {e}") from e


def _extract_json_from_response(content: str, job_id: str | None = None) -> list | dict:
    """
    LLMレスポンスから堅牢にJSONを抽出してパース

    Args:
        content: LLMレスポンステキスト
        job_id: ジョブID（ログ用）

    Returns:
        パースされたJSON（list または dict）

    Raises:
        json.JSONDecodeError: JSON抽出・パースに失敗した場合
        ValueError: 有効なJSONが見つからない場合
    """
    import re

    # 1. マークダウンコードブロックを除去
    if "```json" in content:
        parts = content.split("```json")
        if len(parts) > 1:
            content = parts[1].split("```")[0].strip()
    elif "```" in content:
        parts = content.split("```")
        if len(parts) > 1:
            content = parts[1].split("```")[0].strip()

    # 2. JSON配列またはオブジェクトを正規表現で抽出
    # まず完全な配列を探す
    complete_array_match = re.search(r'\[\s*\{.*?\}\s*\]', content, re.DOTALL)
    if complete_array_match:
        content = complete_array_match.group()
    else:
        # 不完全な配列も探す（レスポンスが途中で切れている場合）
        incomplete_array_match = re.search(r'\[\s*\{.*', content, re.DOTALL)
        if incomplete_array_match:
            content = incomplete_array_match.group()
            # 配列を強制的に閉じる
            if not content.rstrip().endswith(']'):
                # 最後のオブジェクトを閉じる
                if not content.rstrip().endswith('}'):
                    content = content.rstrip().rstrip(',') + '}'
                content = content + ']'
        else:
            # オブジェクトを探す
            obj_match = re.search(r'\{.*\}', content, re.DOTALL)
            if obj_match:
                content = obj_match.group()
            else:
                # 不完全なオブジェクト
                incomplete_obj_match = re.search(r'\{.*', content, re.DOTALL)
                if incomplete_obj_match:
                    content = incomplete_obj_match.group()
                    if not content.rstrip().endswith('}'):
                        content = content.rstrip().rstrip(',') + '}'

    # 3. よくある問題を修正
    # - 末尾のカンマを削除
    content = re.sub(r',\s*}', '}', content)
    content = re.sub(r',\s*\]', ']', content)
    # - 不完全な数値を修正 (例: "score": 0.} -> "score": 0.0})
    content = re.sub(r':\s*(\d+\.)\s*([,}\]])', r': \g<1>0\2', content)
    # - 不完全なキー:値のペアを修正（値がない場合）
    content = re.sub(r':\s*([,}\]])', r': null\1', content)

    try:
        parsed = json.loads(content)
        log_info(f"Successfully parsed JSON: {type(parsed).__name__}", job_id=job_id)
        return parsed
    except json.JSONDecodeError as e:
        # デバッグ用に問題箇所を表示
        error_line = content.split('\n')[e.lineno - 1] if e.lineno <= len(content.split('\n')) else ""
        log_error(
            f"JSON parse failed at line {e.lineno}, col {e.colno}: {e.msg}\n"
            f"Error line: {error_line[:100]}\n"
            f"Full JSON content:\n{content}",
            job_id=job_id
        )
        raise


def _pick_segments_llm(
    transcript_json: list[TranscriptSegment],
    target_num: int,
    min_sec: int,
    max_sec: int,
    title_hint: str | None,
    job_id: str | None
) -> list[SegmentInfo]:
    """
    LLMを使用してセグメントを抽出

    Returns:
        選定されたセグメントリスト
    """
    log_info("Using LLM for segment extraction", job_id=job_id)

    # トランスクリプトをテキストに変換（単語タイムスタンプ付き）
    transcript_lines = []
    for seg in transcript_json:
        if seg.words:
            # 単語レベルのタイムスタンプを付与（精密カット用）
            word_parts = " ".join([
                f"{w.word}({w.end:.1f}s)" for w in seg.words
            ])
            transcript_lines.append(
                f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}\n  単語: {word_parts}"
            )
        else:
            transcript_lines.append(f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
    transcript_text = "\n".join(transcript_lines)

    # プロンプトを構築
    prompt = f"""あなたはYouTubeショート動画のエディターです。
以下の動画の文字起こしから、**本動画への誘導効果が高い**{min_sec}〜{max_sec}秒の区間を{target_num}個選んでください。

## 目的
ショート動画を見た視聴者が「続きが気になる」「本動画を見たい」と思うようにすること。

## ★最重要ルール: 自然なカット境界（これを最優先で守ること）

### 開始地点のルール
- ✅ 文や話題の冒頭から開始する
- ✅ 「では」「さて」「次に」などの接続詞の直後から開始
- ❌ 文の途中から開始しない（視聴者が文脈を失う）

### 終了地点のルール（最重要）
- ✅ 文末（。！？）の直後で終了する — 最も自然
- ✅ 意図的な「引き」: 核心の直前で切る場合は、直前の文は完結させる
- ❌ 単語の途中で切らない（絶対NG）
- ❌ 「〜が」「〜で」「〜して」など助詞・接続助詞の直後で切らない
- ❌ 「〜ということは」「〜なんですけど」のような接続表現の途中で切らない

### 単語タイムスタンプの活用
文字起こしには各単語の終了時刻が付与されています（例: 食べた(12.3s)）。
endの値は、**最後の完結した文の最終単語の終了時刻**を使ってください。
セグメント境界に縛られず、単語単位で精密にカットポイントを指定できます。

## 動画タイプ別ルール

### クイズ・問題系
- ❌ 絶対NG: 問題の途中で切る、回答発表の直前で切る
- ✅ OK: 回答発表後、次の問題の前で切る
- ✅ 誘導カット: 「正解は…」の直前で切り、hook_textで「答えは本動画で！」

### ランキング・TOP○系
- ✅ 意図的に「1位は…」の直前で切るのは効果的
- ✅ hook_text例: 「1位は絶対予想できない！」「衝撃の1位は本動画で」
- ❌ NG: 順位発表の途中（「3位は〇〇で、2位は…」のような中途半端な切り方）

### 会話・トーク系
- ❌ NG: 発言の途中、話題の途中で切る
- ✅ OK: 話題の区切り、相槌の後、笑いの後
- ✅ 誘導: 面白い話の導入部分で切り、「この後とんでもない展開に…」

### 解説・知識系
- ❌ NG: 説明の途中で切る
- ✅ OK: 一つの説明が完結した後
- ✅ 誘導: 核心部分の直前で切り、「驚きの事実は本動画で」

## スコアリング基準（0.0〜1.0）
- 0.9〜1.0: 強い誘導効果 + 開始・終了ともに自然
- 0.7〜0.8: 良い区切り（内容が完結＋興味を引く）
- 0.5〜0.6: 普通（区切りは良いが誘導効果は弱い）
- 0.3〜0.4: 微妙（区切りが不自然）→ これは出力しないでください
- 0.0〜0.2: 不適切（途中で切れている）→ これは出力しないでください

## 動画タイトル
{title_hint or "不明"}

## 文字起こし（単語タイムスタンプ付き）
{transcript_text[:8000]}

## 出力形式
以下のJSON配列のみを返してください（説明文は不要）：
[
  {{
    "start": 開始秒数（float、文の冒頭の単語タイムスタンプを使用）,
    "end": 終了秒数（float、最後の完結文の末尾単語タイムスタンプを使用）,
    "reason": "選定理由（30文字以内）",
    "score": スコア（0.5〜1.0、0.5未満は出力しない）,
    "hook_text": "本動画への誘導テキスト（20文字以内、例：衝撃の結末は本動画で！）",
    "end_text": "カット終了地点の直前5〜10文字（検証用）"
  }}
]

## 注意事項
- start/endは単語タイムスタンプから精密に選択する（セグメント境界に縛られない）
- {min_sec}秒以上{max_sec}秒以内の区間のみ
- 区間の重複は避ける
- hook_textは視聴者が本動画を見たくなる短いフレーズ
- end_textでカット末尾の文が完結しているか必ず自己検証すること
- スコア0.5未満の低品質セグメントは出力しない
"""

    try:
        # Gemini APIを設定
        genai.configure(api_key=config.GEMINI_API_KEY)
        model = genai.GenerativeModel(config.GEMINI_MODEL)

        # プロンプトにシステム指示を含める
        full_prompt = "あなたはYouTubeショート動画の編集アシスタントです。JSON形式で応答してください。\n\n" + prompt

        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE"
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE"
            }
        ]
                
        response = model.generate_content(
            full_prompt,
            safety_settings=safety_settings,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 4000,  # 単語タイムスタンプ+end_text追加分
            }
        )

        content = response.text
        log_info(f"LLM response received ({len(content)} chars)", job_id=job_id)

        # レスポンスが短すぎる場合は詳細をログ出力
        if len(content) < 200:
            log_warning(f"Response too short ({len(content)} chars). Full content: {content}", job_id=job_id)
            candidates_info = response.candidates if hasattr(response, 'candidates') else 'N/A'
            log_warning(f"Response candidates: {candidates_info}", job_id=job_id)
            if hasattr(response, 'prompt_feedback'):
                log_warning(f"Prompt feedback: {response.prompt_feedback}", job_id=job_id)

        # JSONをパース - より堅牢な抽出
        candidates = _extract_json_from_response(content, job_id=job_id)

        # SegmentInfoに変換（単語タイムスタンプにスナップ）
        segments = []
        for cand in candidates:
            start = cand["start"]
            end = cand["end"]

            # 単語タイムスタンプにスナップして精密なカットポイントに補正
            start = _snap_to_word_boundary(transcript_json, start, mode="start")
            end = _snap_to_word_boundary(transcript_json, end, mode="end")

            # 文末（句読点）にスナップしてブツ切り防止
            end = _snap_end_to_sentence_boundary(
                transcript_json, end, min_sec=min_sec,
                start_sec=start, max_sec=max_sec,
            )

            duration = end - start

            # 条件チェック（スナップ後に再検証）
            if min_sec <= duration <= max_sec:
                segments.append(SegmentInfo(
                    start=start,
                    end=end,
                    score=cand.get("score", 0.7),
                    method="llm",
                    reason=cand.get("reason", ""),
                    hook_text=cand.get("hook_text")
                ))

        # 重複除去（重なり>30%）
        segments = _remove_overlapping_segments(segments, overlap_threshold=0.3)

        # スコア順にソートして上位を返す
        segments.sort(key=lambda x: x.score, reverse=True)
        return segments[:target_num]

    except Exception as e:
        log_error(f"LLM extraction error: {e}", job_id=job_id, exc_info=True)
        raise


def _pick_segments_rule_based(
    transcript_json: list[TranscriptSegment],
    video_path: str,
    target_num: int,
    min_sec: int,
    max_sec: int,
    job_id: str | None
) -> list[SegmentInfo]:
    """
    規則ベースでセグメントを抽出（フォールバック）

    Returns:
        選定されたセグメントリスト
    """
    log_info("Using rule-based segment extraction", job_id=job_id)

    segments = []

    # 無音区間を検出
    silence_points = _detect_silence(video_path, job_id=job_id)

    # 文字起こしの句読点と無音を境界候補とする
    boundaries = set()

    # 句読点境界（単語レベルで精密に検出）
    for seg in transcript_json:
        if seg.words:
            for w in seg.words:
                if w.word.rstrip().endswith(("。", "！", "？", ".", "!", "?")):
                    boundaries.add(w.end)
        elif seg.text.endswith(("。", "！", "？", ".", "!", "?")):
            boundaries.add(seg.end)

    # 無音境界
    boundaries.update(silence_points)

    # ソート
    boundaries = sorted(boundaries)

    # 目標秒数の中間値
    target_sec = (min_sec + max_sec) / 2

    # 境界を使って自然な区間を作成
    current_start = 0.0
    total_duration = transcript_json[-1].end if transcript_json else 60.0

    # 境界がない場合は固定尺フォールバック
    if not boundaries:
        log_warning("No boundaries found, using fixed duration", job_id=job_id)
        return _create_fixed_segments(total_duration, target_num, min_sec, max_sec)

    boundaries_list = sorted(list(boundaries))

    while current_start < total_duration and len(segments) < target_num:
        # 目標終了時刻
        target_end = current_start + target_sec

        # 有効な境界（min_sec以上、max_sec以下の範囲）を探す
        valid_boundaries = [
            b for b in boundaries_list
            if current_start < b <= total_duration
            and min_sec <= (b - current_start) <= max_sec
        ]

        if valid_boundaries:
            # 目標時刻に最も近い境界を選択
            best_end = min(valid_boundaries, key=lambda b: abs(b - target_end))
        else:
            # 有効な境界がない場合、min_sec以上の最小境界を探す
            possible_boundaries = [
                b for b in boundaries_list
                if current_start < b <= total_duration
                and (b - current_start) >= min_sec
            ]

            if possible_boundaries:
                best_end = possible_boundaries[0]  # 最初の有効な境界
            else:
                # それでも見つからない場合は強制的に次へ
                current_start = min(
                    [b for b in boundaries_list if b > current_start],
                    default=current_start + target_sec
                )
                continue

        # セグメント作成
        duration = best_end - current_start
        if min_sec <= duration <= max_sec:
            segments.append(SegmentInfo(
                start=current_start,
                end=best_end,
                score=0.6,  # 境界ベースなのでスコア少し高め
                method="rule",
                reason="句読点・無音境界で分割"
            ))
            current_start = best_end
        else:
            # 次の境界から再試行
            current_start = best_end

    # 最低3本を保証
    if len(segments) < 3:
        log_warning(f"Insufficient segments ({len(segments)}), creating fixed-duration segments", job_id=job_id)
        segments = _create_fixed_segments(total_duration, target_num, min_sec, max_sec)

    return segments[:target_num]


def _detect_silence(video_path: str, job_id: str | None = None) -> list[float]:
    """
    ffmpegのsilencedetectで無音区間を検出

    Returns:
        無音終了時刻のリスト（秒）
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", "silencedetect=noise=-30dB:d=0.5",
            "-f", "null",
            "-"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180  # 長い動画対応のため60→180秒に延長
        )

        # stderrから無音終了時刻を抽出
        silence_points = []
        for line in result.stderr.split("\n"):
            if "silence_end:" in line:
                try:
                    # 例: [silencedetect @ ...] silence_end: 12.345 | silence_duration: 1.234
                    end_time = float(line.split("silence_end:")[1].split("|")[0].strip())
                    silence_points.append(end_time)
                except (IndexError, ValueError):
                    continue

        log_info(f"Detected {len(silence_points)} silence points", job_id=job_id)
        return silence_points

    except Exception as e:
        log_warning(f"Silence detection failed: {e}, using empty list", job_id=job_id)
        return []


def _create_fixed_segments(
    total_duration: float,
    target_num: int,
    min_sec: int,
    max_sec: int
) -> list[SegmentInfo]:
    """
    固定尺で均等にセグメントを作成（最終フォールバック）

    Returns:
        セグメントリスト
    """
    segments = []
    segment_duration = (min_sec + max_sec) / 2
    current_start = 0.0

    for i in range(target_num):
        end = min(current_start + segment_duration, total_duration)
        if end - current_start >= min_sec:
            segments.append(SegmentInfo(
                start=current_start,
                end=end,
                score=0.65,
                method="rule",
                reason="固定尺分割（フォールバック）"
            ))
        current_start = end

        if current_start >= total_duration:
            break

    return segments


def _remove_overlapping_segments(
    segments: list[SegmentInfo],
    overlap_threshold: float = 0.3
) -> list[SegmentInfo]:
    """
    重複セグメントを除去（重なり>30%のものを削除）

    Args:
        segments: セグメントリスト
        overlap_threshold: 重複閾値（0.0〜1.0）

    Returns:
        重複を除去したセグメントリスト
    """
    if not segments:
        return []

    # スコア順にソート
    sorted_segments = sorted(segments, key=lambda x: x.score, reverse=True)

    result = []
    for seg in sorted_segments:
        # 既存のセグメントと重複チェック
        has_overlap = False
        for existing in result:
            overlap = _calculate_overlap(seg, existing)
            if overlap > overlap_threshold:
                has_overlap = True
                break

        if not has_overlap:
            result.append(seg)

    return result


def _snap_to_word_boundary(
    transcript_json: list[TranscriptSegment],
    time_sec: float,
    mode: str = "end",
    tolerance: float = 1.5,
) -> float:
    """
    指定時刻を最寄りの単語境界にスナップする

    Args:
        transcript_json: 文字起こしセグメントリスト
        time_sec: スナップ対象の時刻（秒）
        mode: "start"なら単語の開始時刻、"end"なら単語の終了時刻にスナップ
        tolerance: 許容誤差（秒）。この範囲内で最も近い境界を探す

    Returns:
        スナップ後の時刻（秒）
    """
    # 全単語を収集
    all_words = []
    for seg in transcript_json:
        for w in seg.words:
            all_words.append(w)

    if not all_words:
        return time_sec

    # 最も近い単語境界を探す
    best_time = time_sec
    best_dist = tolerance + 1

    for w in all_words:
        target = w.start if mode == "start" else w.end
        dist = abs(target - time_sec)
        if dist < best_dist:
            best_dist = dist
            best_time = target

    return best_time if best_dist <= tolerance else time_sec


def _snap_end_to_sentence_boundary(
    transcript_json: list[TranscriptSegment],
    end_sec: float,
    min_sec: float,
    start_sec: float,
    max_sec: float,
    tolerance: float = 3.0,
) -> float:
    """
    終了時刻を文末（句読点）の直後にスナップする

    句読点（。！？）で終わる単語の終了時刻のうち、
    end_secに最も近いものを選ぶ。

    Args:
        transcript_json: 文字起こしセグメントリスト
        end_sec: 現在の終了時刻
        min_sec: 最小秒数
        start_sec: セグメント開始時刻
        max_sec: 最大秒数
        tolerance: 許容誤差（秒）

    Returns:
        スナップ後の終了時刻
    """
    sentence_endings = []

    for seg in transcript_json:
        if seg.words:
            # 単語レベルで句読点を探す
            for w in seg.words:
                if w.word.rstrip().endswith(("。", "！", "？", ".", "!", "?")):
                    sentence_endings.append(w.end)
        else:
            # 単語情報がない場合はセグメント末尾を使う
            if seg.text.endswith(("。", "！", "？", ".", "!", "?")):
                sentence_endings.append(seg.end)

    if not sentence_endings:
        return end_sec

    # end_secに近い文末を探す（duration制約を守る）
    best_end = end_sec
    best_dist = tolerance + 1

    for se in sentence_endings:
        duration = se - start_sec
        if min_sec <= duration <= max_sec:
            dist = abs(se - end_sec)
            if dist < best_dist:
                best_dist = dist
                best_end = se

    return best_end if best_dist <= tolerance else end_sec


def _calculate_overlap(seg1: SegmentInfo, seg2: SegmentInfo) -> float:
    """
    2つのセグメントの重複率を計算

    Returns:
        重複率（0.0〜1.0）
    """
    start = max(seg1.start, seg2.start)
    end = min(seg1.end, seg2.end)

    if start >= end:
        return 0.0

    overlap_duration = end - start
    min_duration = min(seg1.end - seg1.start, seg2.end - seg2.start)

    return overlap_duration / min_duration if min_duration > 0 else 0.0
