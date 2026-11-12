import os
import json
import glob
import asyncio
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from deep_translator import GoogleTranslator
import edge_tts

YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
EMAIL_USER = os.environ["EMAIL_USER"]
EMAIL_PASS = os.environ["EMAIL_PASS"]

# 各局のYouTubeチャンネルID と 公式ニュースRSSのセット
CHANNELS = {
    "01_BBC_英国": {
        "yt": "UC16niRr50-MSBwiO3YDb3RA",
        "rss": "https://feeds.bbci.co.uk/news/world/rss.xml"
    },
    "02_ABC_米国": {
        "yt": "UCBi2mrWuNuyYy4gbM6fU18Q",
        "rss": "https://abcnews.go.com/abcnews/internationalheadlines"
    },
    "03_AlJazeera_中東": {
        "yt": "UCNye-wNBqNL5ZzHSJj3l8Bg",
        "rss": "https://www.aljazeera.com/xml/rss/all.xml"
    },
    "04_DW_ドイツ": {
        "yt": "UCknLrEdhRCp1aegoMqRaCZg",
        "rss": "https://rss.dw.com/xml/rss-en-world"
    },
    "05_France24_フランス": {
        "yt": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
        "rss": "https://www.france24.com/en/rss"
    },
    "06_RTVE_スペイン": {
        "yt": "UC7QZIf0AyafaWXxHTiuMSZQ",
        "rss": "https://api2.rtve.es/rss/temas_noticias.xml"
    },
    "07_KBS_韓国": {
        "yt": "UCcQTRi69dsVYHN3exePtZ1A",
        "rss": "https://world.kbs.co.kr/rss/rss_news.htm?lang=e"
    },
    "08_CGTN_中国": {
        "yt": "UCgrNz-aEg5VUq4P46F382MA",
        "rss": "https://www.cgtn.com/subscribe/rss/section/world.xml"
    },
    "09_CNA_アジア": {
        "yt": "UC83jt4dlz1Gjl58fzQrrKZg",
        "rss": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6311"
    },
    "10_ABC_豪州": {
        "yt": "UCVgO39Bk5sMo66-6o6Spn6Q",
        "rss": "https://www.abc.net.au/news/feed/51120/rss.xml"
    }
}

VOICE = "ja-JP-NanamiNeural"
PLAYER_URL = "https://okamoto-netizen.github.io/world-news-digest/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_article_text(url):
    """ニュース記事ページから本文パラグラフを抽出する"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        # 短いメニュー文や著作権表示を除き、記事本文らしい段落だけを結合
        meaningful = [p for p in paragraphs if len(p) > 45]
        return " ".join(meaningful[:12])
    except Exception:
        return ""


def fetch_station_news(rss_url):
    """公式RSSからトップニュース3本分の詳細記事を取得して充実した原稿を作る"""
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=10)
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")[:3]
        if not items:
            return None, None

        main_title = ""
        compiled_sections = []

        for idx, item in enumerate(items):
            title_el = item.find("title")
            desc_el = item.find("description")
            link_el = item.find("link")

            title = BeautifulSoup(title_el.text or "", "html.parser").get_text(strip=True) if title_el is not None else ""
            desc = BeautifulSoup(desc_el.text or "", "html.parser").get_text(strip=True) if desc_el is not None else ""
            link = link_el.text.strip() if (link_el is not None and link_el.text) else ""

            if idx == 0:
                main_title = title

            # 1本目のトップニュースはWeb記事の本文まで深く取得し、2・3本目は概要をまとめる
            detail = ""
            if idx == 0 and link:
                detail = fetch_article_text(link)

            body_text = detail if len(detail) > len(desc) else desc
            if title and body_text:
                compiled_sections.append(f"Topic {idx + 1}: {title}. {body_text}")
            elif title:
                compiled_sections.append(f"Topic {idx + 1}: {title}.")

        full_english = "\n".join(compiled_sections)
        return main_title, full_english[:3000]
    except Exception as e:
        print(f"RSS取得エラー ({rss_url}): {e}")
        return None, None


def get_latest_video_id(youtube, channel_id):
    """YouTubeの公式RSS（APIクォータ消費ゼロ）を優先し、失敗時のみAPIで動画IDを取得"""
    try:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        resp = requests.get(rss_url, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                vid_el = entry.find("yt:videoId", ns)
                link_el = entry.find("atom:link", ns)
                href = link_el.attrib.get("href", "") if link_el is not None else ""
                if vid_el is not None and "/shorts/" not in href:
                    return vid_el.text
    except Exception:
        pass

    try:
        res = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            order="date",
            type="video",
            maxResults=5
        ).execute()
        for item in res.get("items", []):
            if item["snippet"].get("liveBroadcastContent") == "none":
                return item["id"]["videoId"]
    except Exception:
        pass
    return None


def translate_long_text(text):
    if not text:
        return ""
    chunks = [text[i:i + 1400] for i in range(0, len(text), 1400)]
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


def main():
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y年%m月%d日")

    os.makedirs("audio", exist_ok=True)
    for old_mp3 in glob.glob("audio/*.mp3"):
        os.remove(old_mp3)

    news_items = []
    program_list_html = []

    for label, cfg in CHANNELS.items():
        station_display = label.split("_", 1)[1].replace("_", " ")
        vid = get_latest_video_id(youtube, cfg["yt"])
        if not vid:
            print(f"動画ID取得失敗（スキップ）: {label}")
            continue

        main_title, raw_article = fetch_station_news(cfg["rss"])
        if not main_title or not raw_article:
            print(f"ニュース記事取得失敗（スキップ）: {label}")
            continue

        title_ja = translate_long_text(main_title)
        body_ja = translate_long_text(raw_article)

        script = f"{station_display}の主要ニュースです。\n{body_ja}"
        audio_rel_path = f"audio/{label}.mp3"
        asyncio.run(generate_audio(script, audio_rel_path))

        news_items.append({
            "station": station_display,
            "title": title_ja,
            "videoId": vid,
            "audioUrl": audio_rel_path,
            "script": script
        })
        program_list_html.append(f"<li><strong>{station_display}</strong>: {title_ja}</li>")
        print(f"生成完了 ({len(body_ja)}文字): {label}")

    if not news_items:
        print("ニュースが取得できませんでした。")
        return

    with open("player.html", "r", encoding="utf-8") as f:
        template = f.read()

    items_json = json.dumps(news_items, ensure_ascii=False)
    html_content = template.replace("__NEWS_DATA__", items_json).replace("__TODAY_STR__", today_str)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【詳細解説版・同時再生】朝のワールドニュース ({today_str})"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_USER

    body_lines = [
        f"<h2>{today_str} 世界の朝刊（公式ニュース記事＋同時再生版）</h2>",
        "<p>各放送局の公式ニュース記事（トップ3項目・詳細本文）を日本語翻訳・音声化しました。</p>",
        f'<p style="margin: 20px 0;"><a href="{PLAYER_URL}" style="background-color: #d32f2f; color: white; padding: 14px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">▶ 映像＋日本語音声 同時再生プレイヤーを開く</a></p>',
        "<h3>本日のラインナップ</h3>",
        f"<ul>{''.join(program_list_html)}</ul>"
    ]
    email_html = "<html><body style='font-family: sans-serif; line-height: 1.6;'>" + "".join(body_lines) + "</body></html>"
    msg.attach(MIMEText(email_html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)

    print("詳細解説版の生成とメール送信が完了しました！")


if __name__ == "__main__":
    main()
