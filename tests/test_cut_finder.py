"""cut_finder.pyのユニットテスト"""
from unittest.mock import Mock, patch

from app.cut_finder import (
    _calculate_overlap,
    _create_fixed_segments,
    _detect_silence,
    _pick_segments_llm,
    _pick_segments_rule_based,
    _remove_overlapping_segments,
    pick_segments,
)
from app.models import SegmentInfo


class TestCalculateOverlap:
    """_calculate_overlap関数のテスト"""

    def test_no_overlap(self):
        """重複なしの場合"""
        seg1 = SegmentInfo(start=0.0, end=10.0, score=0.5, method="rule")
        seg2 = SegmentInfo(start=15.0, end=25.0, score=0.5, method="rule")
        assert _calculate_overlap(seg1, seg2) == 0.0

    def test_partial_overlap(self):
        """部分的に重複している場合"""
        seg1 = SegmentInfo(start=0.0, end=15.0, score=0.5, method="rule")
        seg2 = SegmentInfo(start=10.0, end=20.0, score=0.5, method="rule")
        overlap = _calculate_overlap(seg1, seg2)
        # 重複は5秒、短い方の長さは10秒（seg2-10=10）
        # 実際には両方15秒と10秒なので、短い方は10秒
        assert 0.4 < overlap < 0.6  # およそ50%

    def test_complete_overlap(self):
        """完全に重複している場合"""
        seg1 = SegmentInfo(start=0.0, end=20.0, score=0.5, method="rule")
        seg2 = SegmentInfo(start=5.0, end=15.0, score=0.5, method="rule")
        overlap = _calculate_overlap(seg1, seg2)
        assert overlap == 1.0  # seg2が完全にseg1に含まれる


class TestRemoveOverlappingSegments:
    """_remove_overlapping_segments関数のテスト"""

    def test_no_overlaps(self):
        """重複なしの場合"""
        segments = [
            SegmentInfo(start=0.0, end=10.0, score=0.8, method="llm"),
            SegmentInfo(start=15.0, end=25.0, score=0.7, method="llm"),
            SegmentInfo(start=30.0, end=40.0, score=0.6, method="llm"),
        ]
        result = _remove_overlapping_segments(segments)
        assert len(result) == 3

    def test_with_overlaps(self):
        """重複ありの場合（スコアの高い方が残る）"""
        segments = [
            SegmentInfo(start=0.0, end=20.0, score=0.9, method="llm"),
            SegmentInfo(start=10.0, end=30.0, score=0.5, method="llm"),  # 重複10s/20s = 50% > 30%
            SegmentInfo(start=40.0, end=60.0, score=0.8, method="llm"),
        ]
        result = _remove_overlapping_segments(segments, overlap_threshold=0.3)
        # スコアの高いseg1とseg3が残る
        assert len(result) == 2
        assert result[0].score == 0.9
        assert result[1].score == 0.8


class TestCreateFixedSegments:
    """_create_fixed_segments関数のテスト"""

    def test_sufficient_duration(self):
        """十分な長さがある場合"""
        segments = _create_fixed_segments(
            total_duration=120.0,
            target_num=3,
            min_sec=25,
            max_sec=45
        )
        assert len(segments) == 3
        for seg in segments:
            duration = seg.end - seg.start
            assert 25 <= duration <= 45
            assert seg.method == "rule"

    def test_insufficient_duration(self):
        """短い動画の場合"""
        segments = _create_fixed_segments(
            total_duration=50.0,
            target_num=5,
            min_sec=25,
            max_sec=45
        )
        # 50秒の動画で35秒セグメントは1本しか作れない
        assert len(segments) <= 2


class TestDetectSilence:
    """_detect_silence関数のテスト"""

    @patch('app.cut_finder.subprocess.run')
    def test_detect_silence_success(self, mock_run):
        """無音検出が成功する場合"""
        mock_run.return_value = Mock(
            stderr="[silencedetect @ ...] silence_end: 10.5 | silence_duration: 1.2\n"
                   "[silencedetect @ ...] silence_end: 25.3 | silence_duration: 0.8\n",
            returncode=0
        )
        silence_points = _detect_silence("/fake/video.mp4")
        assert len(silence_points) == 2
        assert 10.5 in silence_points
        assert 25.3 in silence_points

    @patch('app.cut_finder.subprocess.run')
    def test_detect_silence_failure(self, mock_run):
        """無音検出が失敗する場合（空のリストを返す）"""
        mock_run.side_effect = Exception("ffmpeg error")
        silence_points = _detect_silence("/fake/video.mp4")
        assert silence_points == []


class TestPickSegmentsRuleBased:
    """_pick_segments_rule_based関数のテスト"""

    @patch('app.cut_finder._detect_silence')
    def test_rule_based_extraction(self, mock_detect_silence, sample_transcript):
        """規則ベースの抽出"""
        mock_detect_silence.return_value = [12.0, 28.0, 50.0]

        segments = _pick_segments_rule_based(
            transcript_json=sample_transcript,
            video_path="/fake/video.mp4",
            target_num=3,
            min_sec=25,
            max_sec=45,
            job_id=None,
        )

        assert len(segments) >= 1
        for seg in segments:
            duration = seg.end - seg.start
            assert 25 <= duration <= 45
            assert seg.method == "rule"


class TestPickSegmentsLlm:
    """_pick_segments_llm関数のテスト"""

    @patch('app.cut_finder.genai')
    @patch('app.cut_finder.config')
    def test_llm_extraction_success(self, mock_config, mock_genai, sample_transcript):
        """LLM抽出が成功する場合"""
        mock_config.GEMINI_API_KEY = "test_key"
        mock_config.GEMINI_MODEL = "gemini-1.5-flash-latest"

        # Gemini APIのモックレスポンス
        mock_model = Mock()
        mock_genai.GenerativeModel.return_value = mock_model

        mock_response = Mock()
        mock_response.text = '''[
            {"start": 5.0, "end": 35.0, "reason": "重要なポイント", "score": 0.85},
            {"start": 35.0, "end": 60.0, "reason": "具体例", "score": 0.75}
        ]'''
        mock_model.generate_content.return_value = mock_response

        segments = _pick_segments_llm(
            transcript_json=sample_transcript,
            target_num=2,
            min_sec=25,
            max_sec=45,
            title_hint="テスト動画",
            job_id=None,
        )

        assert len(segments) <= 2
        for seg in segments:
            assert seg.method == "llm"
            assert 25 <= (seg.end - seg.start) <= 45

    @patch('app.cut_finder.genai')
    @patch('app.cut_finder.config')
    def test_llm_extraction_with_markdown(self, mock_config, mock_genai, sample_transcript):
        """LLMがマークダウンコードブロックで返す場合"""
        mock_config.GEMINI_API_KEY = "test_key"
        mock_config.GEMINI_MODEL = "gemini-1.5-flash-latest"

        mock_model = Mock()
        mock_genai.GenerativeModel.return_value = mock_model

        mock_response = Mock()
        mock_response.text = '''```json
        [
            {"start": 10.0, "end": 40.0, "reason": "テスト", "score": 0.8}
        ]
        ```'''
        mock_model.generate_content.return_value = mock_response

        segments = _pick_segments_llm(
            transcript_json=sample_transcript,
            target_num=1,
            min_sec=25,
            max_sec=45,
            title_hint=None,
            job_id=None,
        )

        assert len(segments) == 1
        assert segments[0].method == "llm"


class TestPickSegments:
    """pick_segments関数のテスト（メイン関数）"""

    @patch('app.cut_finder._pick_segments_llm')
    @patch('app.cut_finder.config')
    def test_llm_mode_success(self, mock_config, mock_llm_func, sample_transcript):
        """LLMモードが成功する場合"""
        mock_config.GEMINI_API_KEY = "test_key"
        mock_llm_func.return_value = [
            SegmentInfo(start=5.0, end=35.0, score=0.8, method="llm", reason="test"),
            SegmentInfo(start=40.0, end=70.0, score=0.7, method="llm", reason="test2"),
            SegmentInfo(start=75.0, end=100.0, score=0.6, method="llm", reason="test3"),
        ]

        segments = pick_segments(
            transcript_json=sample_transcript,
            video_path="/fake/video.mp4",
            target_num=3,
            force_rule_based=False
        )

        assert len(segments) == 3
        assert all(seg.method == "llm" for seg in segments)

    @patch('app.cut_finder._pick_segments_rule_based')
    @patch('app.cut_finder.config')
    def test_force_rule_based(self, mock_config, mock_rule_func, sample_transcript):
        """force_rule_based=Trueの場合"""
        mock_config.GEMINI_API_KEY = "test_key"
        mock_rule_func.return_value = [
            SegmentInfo(start=0.0, end=30.0, score=0.5, method="rule"),
            SegmentInfo(start=35.0, end=65.0, score=0.5, method="rule"),
        ]

        segments = pick_segments(
            transcript_json=sample_transcript,
            video_path="/fake/video.mp4",
            target_num=2,
            force_rule_based=True
        )

        assert len(segments) == 2
        assert all(seg.method == "rule" for seg in segments)

    @patch('app.cut_finder._pick_segments_llm')
    @patch('app.cut_finder._pick_segments_rule_based')
    @patch('app.cut_finder.config')
    def test_llm_fallback_to_rule(self, mock_config, mock_rule_func, mock_llm_func, sample_transcript):
        """LLMが失敗して規則ベースにフォールバックする場合"""
        mock_config.GEMINI_API_KEY = "test_key"
        mock_llm_func.side_effect = Exception("LLM error")
        mock_rule_func.return_value = [
            SegmentInfo(start=0.0, end=30.0, score=0.5, method="rule"),
        ]

        segments = pick_segments(
            transcript_json=sample_transcript,
            video_path="/fake/video.mp4",
            target_num=1,
            force_rule_based=False
        )

        # フォールバックが動作
        assert len(segments) >= 1
