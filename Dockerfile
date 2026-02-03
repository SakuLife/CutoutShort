FROM python:3.11-slim

# システムパッケージをインストール（日本語フォント含む）
RUN apt-get update && apt-get install -y \
    ffmpeg \
    wget \
    curl \
    unzip \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# yt-dlpをインストール（最新版）
RUN wget -O /usr/local/bin/yt-dlp https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp

# Deno（yt-dlp 2025.11以降でYouTube JSチャレンジ解決に必須）
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR="/root/.cache/deno"
ENV PATH="/root/.deno/bin:$PATH"

# PO Token Provider (Rust版バイナリ) - Bot検出回避用
RUN wget -O /usr/local/bin/bgutil-pot \
    https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-pot-linux-x86_64 && \
    chmod a+rx /usr/local/bin/bgutil-pot

# PO Token yt-dlpプラグイン（Rust版zip）- pip版（Brainicism）とは互換性なし
RUN mkdir -p /root/.yt-dlp/plugins && \
    wget -O /root/.yt-dlp/plugins/bgutil-ytdlp-pot-provider-rs.zip \
    https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/latest/download/bgutil-ytdlp-pot-provider-rs.zip

# 作業ディレクトリを設定
WORKDIR /app

# 依存関係をコピーしてインストール
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# エントリーポイント
RUN chmod +x /app/entrypoint.sh

# 環境変数
ENV PYTHONUNBUFFERED=1
ENV TMP_DIR=/tmp

# Cloud Run Jobs: PO Tokenサーバー起動後にスケジューラー実行
CMD ["/app/entrypoint.sh"]
