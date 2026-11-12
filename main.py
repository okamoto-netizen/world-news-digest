import os
import json
import glob
import asyncio
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from deep_translator import GoogleTranslator
import edge_tts

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]

CHANNELS = {
    "01_BBC_英国": "UC16niRr50-MSBwiO3YDb3RA",
    "02_ABC_米国": "UCBi2mrWuNuyYy4gbM6fU18Q",
    "03_AlJazeera_中東": "UCNye-wNBqNL5ZzHSJj3l8Bg",
    "04_DW_ドイツ": "UCknLrEdhRCp1aegoMqRaCZg",
    "05_France24_フランス": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "06_RTVE_スペイン": "UC7QZIf0AyafaWXxHTiuMSZQ",
    "07_KBS_韓国": "UCcQTRi69dsVYHN3exePtZ1A",
    "08_CGTN_中国": "UCgrNz-aEg5VUq4P46F382MA",
    "09_CNA_アジア": "UC83jt4dlz1Gjl58fzQrrKZg",
    "10_ABC_豪州": "UCVgO39Bk5sMo66-6o6Spn6Q",
}

VOICE = "ja-JP-NanamiNeural"
PLAYER_URL = "https://okamoto-netizen.github.io/world-news-digest/"


def fetch_full_transcript(video_id):
    """動画全体（最大約6分・4500文字分）の字幕テキストをしっかり取得する"""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        lines = [item["text"] for item in fetched if item["start"] <= 360.0]
        full_text = " ".join(lines).strip()
        return full_text[:4500]
    except Exception:
        return None


def translate_long_text(text):
    """長文を1,500文字ずつに分割して確実に日本語へ翻訳する"""
    if not text:
        return ""
    chunks = [text[i:i + 1500] for i in range(0, len(text), 1500)]
    translated_parts = []
    for chunk in chunks:
        try:
            res = GoogleTranslator(source="auto", target="ja").translate(chunk)
            if res:
                translated_parts.append(res)
        except Exception:
            translated_parts.append(chunk)
    return "".join(translated_parts)


async def generate_audio(script_text, output_path):
    communicate = edge_tts.Communicate(script_text, VOICE, rate="+15%")
    await communicate.save(output_path)


def build_player_html(today_str, news_items):
    """YouTube映像とMP3音声を同時スタート・連続再生するWebプレイヤーを生成する"""
    items_json = json.dumps(news_items, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>世界の朝刊 同時通訳プレイヤー ({today_str})</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #f5f5f5; margin: 0; padding: 16px; }}
    .container {{ max-width: 820px; margin: 0 auto; }}
    h1 {{ font-size: 1.3rem; margin-bottom: 12px; color: #fff; }}
    .video-box {{ position: relative; width: 100%; padding-top: 56.25%; background: #000; border-radius: 8px; overflow: hidden; }}
    #yt-player {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0; align-items: center; background: #1e1e1e; padding: 12px; border-radius: 8px; }}
    button {{ background: #d32f2f; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-size: 0.95rem; font-weight: bold; cursor: pointer; }}
    button.secondary {{ background: #333; }}
    button:hover {{ opacity: 0.9; }}
    .now-playing {{ font-size: 0.95rem; color: #ff8a80; font-weight: bold; margin-bottom: 8px; }}
    .script-box {{ background: #1e1e1e; padding: 14px; border-radius: 8px; font-size: 0.95rem; line-height: 1.7; color: #eee; margin-bottom: 16px; max-height: 220px; overflow-y: auto; }}
    .playlist {{ list-style: none; padding: 0; margin: 0; }}
    .playlist li {{ background: #1e1e1e; margin-bottom: 8px; padding: 12px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 10px; cursor: pointer; border-left: 4px solid transparent; }}
    .playlist li.active {{ border-left-color: #d32f2f; background: #2a2020; }}
    .station {{ font-size: 0.8rem; color: #aaa; }}
    .title {{ font-size: 0.95rem; font-weight: bold; margin-top: 2px; }}
  </style>
</head>
<body>
<div class="container">
  <h1>🌍 世界の朝刊 NHK風同時通訳プレイヤー ({today_str})
