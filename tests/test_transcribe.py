"""transcribe.pyのユニットテスト"""
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.transcribe import (
    TranscribeError,
    _format_subtitle_text,
    _format_timestamp_srt,
    get_video_duration,
    transcribe_to_srt,
)


class TestFormatTimestampSrt:
    """_format_timestamp_srt関数のテスト"""

    def test_zero_seconds(self):
        """0秒の場合"""
        assert _format_timestamp_srt(0.0) == "00:00:00,000"

    def test_fractional_seconds(self):
        """小数秒の場合"""
        assert _format_timestamp_srt(12.345) == "00:00:12,345"

    def test_minutes_and_seconds(self):
        """分と秒がある場合"""
        assert _format_timestamp_srt(125.678) == "00:02:05,678"

    def test_hours_minutes_seconds(self):
        """時・分・秒がある場合"""
        assert _format_timestamp_srt(3661.5) == "01:01:01,500"


class TestFormatSubtitleText:
    """_format_subtitle_text関数のテスト"""

    def test_short_text(self):
        """短いテキストの場合"""
        text = "こんにちは。"
        result = _format_subtitle_text(text)
        assert result == "こんにちは。"

    def test_text_with_punctuation(self):
        """句読点で区切られるテキスト"""
        text = "これは最初の文です。次が2番目の文です。"
        result = _format_subtitle_text(text, max_lines=2)
        lines = result.split("\n")
        assert len(lines) <= 2
        assert "。" in result

    def test_long_text_truncation(self):
        """長いテキストが最大行数で切られる"""
        text = "A" * 100
        result = _format_subtitle_text(text, max_lines=2, max_chars_per_line=30)
        lines = result.split("\n")
        assert len(lines) <= 2


class TestGetVideoDuration:
    """get_video_duration関数のテスト"""

    @patch('app.transcribe.subprocess.run')
    def test_valid_video(self, mock_run):
        """正常な動画の場合"""
        mock_run.return_value = Mock(stdout="120.5\n", returncode=0)
        duration = get_video_duration("/fake/video.mp4")
        assert duration == 120.5

    @patch('app.transcribe.subprocess.run')
    def test_ffprobe_error(self, mock_run):
        """ffprobeがエラーを返す場合"""
        mock_run.side_effect = Exception("ffprobe failed")
        with pytest.raises(TranscribeError):
            get_video_duration("/fake/video.mp4")


class TestTranscribeToSrt:
    """transcribe_to_srt関数のテスト"""

    @patch('app.transcribe.WhisperModel')
    def test_file_not_found(self, mock_whisper):
        """入力ファイルが存在しない場合"""
        with pytest.raises(TranscribeError, match="Input file not found"):
            transcribe_to_srt("/nonexistent/video.mp4")

    @patch('app.transcribe.WhisperModel')
    @patch('app.transcribe.Path')
    def test_transcribe_success(self, mock_path, mock_whisper_class, temp_dir):
        """正常に文字起こしが成功する場合"""
        # 入力ファイルの存在チェックをパス
        mock_path.return_value.exists.return_value = True
        mock_path.return_value.with_suffix.return_value = temp_dir / "test.srt"

        # Whisperモデルのモック
        mock_model = MagicMock()
        mock_whisper_class.return_value = mock_model

        # 文字起こし結果のモック
        mock_segment1 = Mock()
        mock_segment1.start = 0.0
        mock_segment1.end = 5.0
        mock_segment1.text = "テストセグメント1"

        mock_segment2 = Mock()
        mock_segment2.start = 5.0
        mock_segment2.end = 10.0
        mock_segment2.text = "テストセグメント2"

        mock_info = Mock()
        mock_info.language = "ja"
        mock_info.language_probability = 0.95
        mock_info.duration = 10.0

        mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], mock_info)

        # 実行
        input_file = temp_dir / "test_video.mp4"
        input_file.touch()  # ファイルを作成

        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_open.return_value.__enter__.return_value = mock_file

            srt_path, transcript_json = transcribe_to_srt(str(input_file))

            # 検証
            assert len(transcript_json) == 2
            assert transcript_json[0].start == 0.0
            assert transcript_json[0].end == 5.0
            assert transcript_json[0].text == "テストセグメント1"

    @patch('app.transcribe.WhisperModel')
    def test_transcribe_whisper_error(self, mock_whisper_class):
        """Whisperがエラーを返す場合"""
        mock_whisper_class.side_effect = Exception("Whisper error")

        # 一時ファイルを作成
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with pytest.raises(TranscribeError):
                transcribe_to_srt(tmp_path)
        finally:
            Path(tmp_path).unlink()


class TestTranscribeIntegration:
    """統合テスト（実際のファイルがある場合のみ）"""

    @pytest.mark.skip(reason="実際の動画ファイルが必要")
    def test_transcribe_real_video(self, test_data_dir):
        """実際の動画ファイルで文字起こしをテスト"""
        video_path = test_data_dir / "sample_video.mp4"
        if not video_path.exists():
            pytest.skip("テスト動画ファイルが存在しません")

        srt_path, transcript_json = transcribe_to_srt(str(video_path))

        # SRTファイルが作成されているか確認
        assert Path(srt_path).exists()
        assert len(transcript_json) > 0

        # タイムスタンプが昇順か確認
        for i in range(len(transcript_json) - 1):
            assert transcript_json[i].end <= transcript_json[i + 1].start
