import requests
import asyncio
from pyrogram import Client, filters
import requests, os, sys, re
import math
import json, asyncio
from config import CHANNEL_ID
import subprocess
import datetime
import zipfile
import time
from datetime import datetime, timedelta
from Extractor import app
from pyrogram import filters
from subprocess import getstatusoutput
log_channel = CHANNEL_ID


# ===================== MOBILE HEADERS (from working clone - Vedstudys.txt) =====================
def get_pw_headers(token):
    """Get properly configured MOBILE headers for PW API access.
    Based on Vedstudys.txt working reference with proper device-meta."""
    return {
        "client-id": "5eb393ee95fab7468a79d189",
        "client-type": "MOBILE",
        "client-version": "538",
        "device-meta": '{"APP_VERSION":"538","APP_VERSION_NAME":"15.32.0","DEVICE_MAKE":"Samsung","DEVICE_MODEL":"SM-A707F","OS_VERSION":"11","PACKAGE_NAME":"xyz.penpencil.physicswala","network":"wifi_data","carrier":"UNDEFINED"}',
        "randomId": "3d3b49f068728fa3",
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://android.pw.live",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A707F Build/RP1A.200720.012)"
    }


def get_login_headers():
    """Headers for login/OTP operations"""
    return {
        "client-id": "5eb393ee95fab7468a79d189",
        "client-version": "12.84",
        "Client-Type": "MOBILE",
        "randomId": "e4307177362e86f1",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json"
    }


# ===================== VIDEO URL EXTRACTOR (from Vedstudys reference) =====================
def extract_video_data(schedule_details_data):
    """Extract MPD/CloudFront video URL with DRM keys from schedule-details response.
    Based on Vedstudys.txt VIDEO_DATA format reference."""
    video_info = {}
    if not schedule_details_data or not schedule_details_data.get("data"):
        return video_info

    data = schedule_details_data["data"]
    video_details = data.get("videoDetails", {})

    if video_details:
        # Primary: Get the MPD URL (CloudFront signed URL)
        video_url = video_details.get("videoUrl") or video_details.get("url") or ""
        if video_url and ".mpd" in video_url.lower():
            video_info["mpd_url"] = video_url

        # Also check for embedCode as fallback
        embed_code = video_details.get("embedCode", "")
        if embed_code and not video_info.get("mpd_url"):
            # Try to extract URL from embedCode if it's a URL
            if embed_code.startswith("http"):
                video_info["video_url"] = embed_code

        # Extract DRM/ClearKey info if available
        drm_type = video_details.get("drmType", "")
        key_id = video_details.get("keyId", "") or video_details.get("kid", "")
        if drm_type and key_id:
            video_info["drm_type"] = drm_type
            video_info["key_id"] = key_id

        # Get video ID for reference
        vid = video_details.get("id", "") or video_details.get("_id", "")
        if vid:
            video_info["video_id"] = vid

    # Also check for direct url in data
    if not video_info.get("mpd_url") and not video_info.get("video_url"):
        direct_url = data.get("url", "")
        if direct_url:
            video_info["video_url"] = direct_url

    return video_info


def format_video_line(topic, video_info):
    """Format video data into extractable line with all info"""
    lines = []
    topic_clean = topic.replace(":", "_").replace("/", "-")

    if video_info.get("mpd_url"):
        # MPD format with DRM keys
        line = f"{topic_clean}:{video_info['mpd_url']}"
        if video_info.get("drm_type") and video_info.get("key_id"):
            line += f" | DRM:{video_info['drm_type']} | KID:{video_info['key_id']}"
        lines.append(line)
    elif video_info.get("video_url"):
        lines.append(f"{topic_clean}:{video_info['video_url']}")

    return lines


# ===================== CONTENT FETCH WITH SCHEDULE-DETAILS =====================
def fetch_content_with_details(batch_id, subject_id, topic_id, headers, content_type="videos"):
    """Fetch content list then get schedule-details for each to extract proper video URLs"""
    all_lines = []
    try:
        page = 1
        while page <= 15:  # safety limit
            url = f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/contents"
            params = {
                "tag": topic_id,
                "contentType": content_type,
                "page": page
            }
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                schedule_id = item.get("_id", "")
                topic = item.get("topic", "Unknown").replace(":", "_").replace("/", "-")

                # Get schedule-details for proper video URL
                detail_url = f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/schedule/{schedule_id}/schedule-details"
                try:
                    detail_resp = requests.get(detail_url, headers=headers, timeout=30)
                    if detail_resp.status_code == 200:
                        detail_data = detail_resp.json()
                        video_info = extract_video_data(detail_data)
                        lines = format_video_line(topic, video_info)
                        all_lines.extend(lines)

                        # Also extract notes/attachments
                        if detail_data and detail_data.get("data"):
                            hw_ids = detail_data["data"].get("homeworkIds", [])
                            for hw in hw_ids:
                                att_ids = hw.get("attachmentIds", [])
                                hw_topic = hw.get("topic", topic).replace(":", "_").replace("/", "-")
                                for att in att_ids:
                                    base_url = att.get("baseUrl", "")
                                    key = att.get("key", "")
                                    name = att.get("name", hw_topic).replace(":", "_").replace("/", "-")
                                    if base_url and key:
                                        all_lines.append(f"{name}:{base_url}{key}")
                    else:
                        # Fallback: use basic URL from item if schedule-details fails
                        basic_url = item.get("url", "")
                        if basic_url:
                            all_lines.append(f"{topic}:{basic_url}")
                        # Also check homework from item
                        for hw in item.get("homeworkIds", []):
                            for att in hw.get("attachmentIds", []):
                                name = att.get("name", topic).replace(":", "_").replace("/", "-")
                                base_url = att.get("baseUrl", "")
                                key = att.get("key", "")
                                if key:
                                    all_lines.append(f"{name}:{base_url}{key}")
                except Exception as e:
                    # Fallback to basic URL
                    basic_url = item.get("url", "")
                    if basic_url:
                        all_lines.append(f"{topic}:{basic_url}")

            if not data.get("hasMore", True):
                break
            page += 1

    except Exception as e:
        pass

    return all_lines


# ===================== TODAY'S CLASS FETCH =====================
def fetch_today_schedule(batch_id, target_date, headers):
    """Fetch scheduled classes for a specific date from PW calendar API.
    Uses proper epoch-based date filtering."""
    all_schedules = []
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        # Start of day and end of day in epoch milliseconds
        start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_epoch = int(start_dt.timestamp() * 1000)
        end_epoch = int(end_dt.timestamp() * 1000)

        # Try v2 schedule endpoint with proper date range
        url = f"https://api.penpencil.co/v2/batches/{batch_id}/schedule"
        params = {
            "startDate": start_epoch,
            "endDate": end_epoch,
            "page": 1
        }
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("data"):
                items = data["data"]
                for item in items:
                    item["_source"] = "v2-schedule"
                all_schedules.extend(items)

        # Also try batch-contents as fallback
        if not all_schedules:
            url2 = f"https://api.penpencil.co/v2/batches/{batch_id}/batch-contents"
            params2 = {
                "startDate": start_epoch,
                "endDate": end_epoch,
                "page": 1
            }
            resp2 = requests.get(url2, headers=headers, params=params2, timeout=30)
            if resp2.status_code == 200:
                data2 = resp2.json()
                if data2.get("success") and data2.get("data"):
                    items = data2["data"]
                    for item in items:
                        item["_source"] = "v2-batch-contents"
                    all_schedules.extend(items)

        # Filter to only items matching target_date
        filtered = []
        for item in all_schedules:
            item_date = item.get("date") or item.get("startTime") or item.get("scheduleDate") or ""
            if target_date in str(item_date):
                filtered.append(item)
            elif not item_date:
                # If no date field, include it (might be from correct range)
                filtered.append(item)

        return filtered if filtered else all_schedules

    except Exception as e:
        return all_schedules


def process_today_class(batch_id, batch_name, target_date, headers, bot_link):
    """Process Today's Class extraction - fetch scheduled content for target date"""
    # Get batch details to find subjects
    detail_url = f"https://api.penpencil.co/v2/batches/{batch_id}/details"
    batch_resp = requests.get(detail_url, headers=headers, timeout=30).json()

    if not batch_resp or not batch_resp.get("success"):
        return None, None, "Failed to fetch batch details"

    subjects = batch_resp.get("data", {}).get("subjects", [])
    if not subjects:
        return None, None, "No subjects found in batch"

    # Fetch schedule
    schedules = fetch_today_schedule(batch_id, target_date, headers)
    if not schedules:
        return None, None, f"No classes scheduled for {target_date}"

    # Build subject lookup
    subject_map = {}
    for subj in subjects:
        sid = subj.get("_id")
        sname = subj.get("subject", "Unknown").replace("/", "-")
        subject_map[sid] = sname

    # Process each scheduled item
    all_urls = []
    structured_data = {}
    json_data = {batch_name: {}}

    clean_batch_name = batch_name.replace('/', '_').replace(':', '_').replace('|', '_').replace('?', '_')
    file_path_base = f"today_{target_date}_{clean_batch_name}"

    for schedule_item in schedules:
        # Extract subject_id - handle various formats
        raw_subject = schedule_item.get("subject", "")
        subject_id = ""
        if isinstance(raw_subject, list) and raw_subject:
            first = raw_subject[0]
            subject_id = first.get("_id", "") if isinstance(first, dict) else str(first)
        elif isinstance(raw_subject, dict):
            subject_id = raw_subject.get("_id", "")
        else:
            subject_id = str(raw_subject) if raw_subject else ""

        # Try to get subject_id from other fields
        if not subject_id:
            subject_id = schedule_item.get("subjectId", "") or schedule_item.get("batchSubjectId", "")

        schedule_id = schedule_item.get("_id", "")
        topic = schedule_item.get("topic", schedule_item.get("name", "Unknown Topic")).replace("/", "-").replace(":", "-")
        start_time = schedule_item.get("startTime", schedule_item.get("startDate", ""))
        end_time = schedule_item.get("endTime", schedule_item.get("endDate", ""))
        content_type_tag = schedule_item.get("contentType", schedule_item.get("type", "unknown"))

        subject_name = subject_map.get(subject_id, "")
        if not subject_name:
            # Try to get from raw subject dict
            if isinstance(raw_subject, dict):
                subject_name = raw_subject.get("subject", raw_subject.get("name", ""))
            if not subject_name:
                subject_name = schedule_item.get("subjectName", "Unknown Subject")
        subject_name = subject_name.replace("/", "-")

        if subject_name not in structured_data:
            structured_data[subject_name] = []
        if subject_name not in json_data[batch_name]:
            json_data[batch_name][subject_name] = {}

        # Fetch schedule-details for video URL
        video_lines = []
        notes_lines = []

        if subject_id and schedule_id:
            detail_url = f"https://api.penpencil.co/v2/batches/{batch_id}/subject/{subject_id}/schedule/{schedule_id}/schedule-details"
            try:
                detail_resp = requests.get(detail_url, headers=headers, timeout=30)
                if detail_resp.status_code == 200:
                    detail_data = detail_resp.json()
                    video_info = extract_video_data(detail_data)
                    video_lines = format_video_line(topic, video_info)

                    # Extract notes
                    if detail_data and detail_data.get("data"):
                        for hw in detail_data["data"].get("homeworkIds", []):
                            for att in hw.get("attachmentIds", []):
                                name = att.get("name", topic).replace(":", "_").replace("/", "-")
                                base_url = att.get("baseUrl", "")
                                key = att.get("key", "")
                                if base_url and key:
                                    notes_lines.append(f"{name}:{base_url}{key}")
            except Exception:
                pass

        # Fallback: check if schedule item itself has URL
        if not video_lines:
            item_url = schedule_item.get("url", "")
            if item_url:
                video_lines.append(f"{topic}:{item_url}")

        all_urls.extend(video_lines)
        all_urls.extend(notes_lines)

        item_data = {
            "topic": topic,
            "start_time": start_time,
            "end_time": end_time,
            "content_type": content_type_tag,
            "videos": video_lines,
            "notes": notes_lines
        }
        structured_data[subject_name].append(item_data)

        # JSON data
        topic_key = f"{topic} ({start_time})"
        json_data[batch_name][subject_name][topic_key] = {}
        if video_lines:
            json_data[batch_name][subject_name][topic_key]["videos"] = video_lines
        if notes_lines:
            json_data[batch_name][subject_name][topic_key]["notes"] = notes_lines

    # === CREATE OUTPUT FILES ===

    # 1. ZIP file
    zip_path = f"{file_path_base}.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.writestr("Telegram Bot/Extractor Bot.txt", f"Extractor Bot:{bot_link}")

        for subject_name, items in structured_data.items():
            zipf.writestr(f"{subject_name}/", "")
            for item in items:
                topic = item["topic"]
                time_slot = item["start_time"]
                folder_name = f"{subject_name}/{topic}_{time_slot}"

                if item["videos"]:
                    content_text = "\n".join(item["videos"])
                    zipf.writestr(f"{folder_name}/videos.txt", content_text.encode('utf-8'))
                if item["notes"]:
                    content_text = "\n".join(item["notes"])
                    zipf.writestr(f"{folder_name}/notes.txt", content_text.encode('utf-8'))

    # 2. JSON file
    json_path = f"{file_path_base}.json"
    json_data[batch_name]["Telegram Bot"] = {"Extractor Bot": bot_link}
    json_data[batch_name]["date"] = target_date
    json_data[batch_name]["total_schedules"] = len(schedules)
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=4)

    # 3. TXT file
    txt_path = f"{file_path_base}.txt"
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"Extractor Bot:{bot_link}\n")
        f.write(f"=== {batch_name} - Classes for {target_date} ===\n\n")
        for subject_name, items in structured_data.items():
            f.write(f"\n--- {subject_name} ---\n")
            for item in items:
                f.write(f"\n📚 {item['topic']}\n")
                f.write(f"⏰ {item['start_time']} - {item['end_time']}\n")
                if item["videos"]:
                    f.write("\n[Videos]\n")
                    f.write("\n".join(item["videos"]) + "\n")
                if item["notes"]:
                    f.write("\n[Notes]\n")
                    f.write("\n".join(item["notes"]) + "\n")

    # 4. HTML file
    html_path = f"{file_path_base}.html"
    html_content = generate_today_html(batch_name, target_date, structured_data, schedules, bot_link, len(all_urls))
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return all_urls, file_path_base, len(schedules), None


def generate_today_html(batch_name, target_date, structured_data, raw_schedules, bot_link, total_links):
    """Generate HTML output for Today's Class"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{batch_name} - {target_date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: rgba(255,255,255,0.95); border-radius: 20px; padding: 30px; margin-bottom: 30px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center; }}
        .header h1 {{ color: #333; font-size: 2em; margin-bottom: 10px; }}
        .header .date {{ color: #667eea; font-size: 1.2em; font-weight: 600; }}
        .header .stats {{ display: flex; justify-content: center; gap: 30px; margin-top: 20px; flex-wrap: wrap; }}
        .stat-box {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 15px 25px; border-radius: 15px; text-align: center; }}
        .stat-box .number {{ font-size: 1.8em; font-weight: bold; }}
        .stat-box .label {{ font-size: 0.9em; opacity: 0.9; }}
        .subject-card {{ background: rgba(255,255,255,0.95); border-radius: 20px; padding: 25px; margin-bottom: 25px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }}
        .subject-title {{ color: #667eea; font-size: 1.5em; font-weight: 700; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 3px solid #667eea; }}
        .class-item {{ background: #f8f9ff; border-radius: 15px; padding: 20px; margin-bottom: 15px; border-left: 5px solid #667eea; }}
        .class-time {{ color: #764ba2; font-weight: 600; font-size: 0.95em; margin-bottom: 8px; }}
        .class-topic {{ color: #333; font-size: 1.1em; font-weight: 600; margin-bottom: 15px; }}
        .content-section {{ margin-top: 12px; }}
        .content-title {{ color: #555; font-weight: 600; font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .link-list {{ list-style: none; }}
        .link-list li {{ background: white; padding: 10px 15px; margin-bottom: 8px; border-radius: 10px; font-size: 0.9em; word-break: break-all; border: 1px solid #e0e0e0; }}
        .link-list li a {{ color: #667eea; text-decoration: none; }}
        .link-list li a:hover {{ text-decoration: underline; }}
        .footer {{ text-align: center; color: rgba(255,255,255,0.8); margin-top: 30px; padding: 20px; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 0.75em; font-weight: 600; text-transform: uppercase; }}
        .badge-video {{ background: #e3f2fd; color: #1976d2; }}
        .badge-note {{ background: #f3e5f5; color: #7b1fa2; }}
        @media (max-width: 768px) {{
            .header h1 {{ font-size: 1.5em; }}
            .stats {{ gap: 15px; }}
            .subject-card {{ padding: 18px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📚 {batch_name}</h1>
            <div class="date">📅 {target_date}</div>
            <div class="stats">
                <div class="stat-box">
                    <div class="number">{len(raw_schedules)}</div>
                    <div class="label">Classes</div>
                </div>
                <div class="stat-box">
                    <div class="number">{len(structured_data)}</div>
                    <div class="label">Subjects</div>
                </div>
                <div class="stat-box">
                    <div class="number">{total_links}</div>
                    <div class="label">Total Links</div>
                </div>
            </div>
        </div>
"""

    for subject_name, items in structured_data.items():
        html += f"""
        <div class="subject-card">
            <div class="subject-title">📖 {subject_name}</div>
"""
        for item in items:
            time_display = f"{item['start_time']} - {item['end_time']}" if item['end_time'] else item['start_time']
            html += f"""
            <div class="class-item">
                <div class="class-time">⏰ {time_display}</div>
                <div class="class-topic">{item['topic']}</div>
"""
            if item['videos']:
                html += """
                <div class="content-section">
                    <div class="content-title"><span class="badge badge-video">Videos</span></div>
                    <ul class="link-list">
"""
                for link in item['videos']:
                    parts = link.split(":", 1)
                    if len(parts) == 2:
                        name, url = parts
                        html += f"                        <li><strong>{name}</strong><br><a href='{url}' target='_blank'>{url}</a></li>\n"
                    else:
                        html += f"                        <li>{link}</li>\n"
                html += "                    </ul>\n                </div>\n"

            if item['notes']:
                html += """
                <div class="content-section">
                    <div class="content-title"><span class="badge badge-note">Notes</span></div>
                    <ul class="link-list">
"""
                for link in item['notes']:
                    parts = link.split(":", 1)
                    if len(parts) == 2:
                        name, url = parts
                        html += f"                        <li><strong>{name}</strong><br><a href='{url}' target='_blank'>{url}</a></li>\n"
                    else:
                        html += f"                        <li>{link}</li>\n"
                html += "                    </ul>\n                </div>\n"

            html += "            </div>\n"

        html += "        </div>\n"

    html += f"""
        <div class="footer">
            <p>Extracted by Extractor Bot | {bot_link}</p>
        </div>
    </div>
</body>
</html>"""
    return html


# ===================== FULL BATCH HTML GENERATOR =====================
def generate_full_batch_html(batch_name, subjects_data, all_urls, bot_link, expiry_date):
    """Generate HTML output for Full Batch extraction"""
    video_count = len(re.findall(r'\.(m3u8|mpd|mp4)', "\n".join(all_urls)))
    pdf_count = len(re.findall(r'\.pdf', "\n".join(all_urls)))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{batch_name} - Full Batch Content</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); min-height: 100vh; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{ background: rgba(255,255,255,0.95); border-radius: 20px; padding: 30px; margin-bottom: 30px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); text-align: center; }}
        .header h1 {{ color: #333; font-size: 2em; margin-bottom: 10px; }}
        .header .subtitle {{ color: #11998e; font-size: 1.2em; font-weight: 600; }}
        .header .stats {{ display: flex; justify-content: center; gap: 30px; margin-top: 20px; flex-wrap: wrap; }}
        .stat-box {{ background: linear-gradient(135deg, #11998e, #38ef7d); color: white; padding: 15px 25px; border-radius: 15px; text-align: center; }}
        .stat-box .number {{ font-size: 1.8em; font-weight: bold; }}
        .stat-box .label {{ font-size: 0.9em; opacity: 0.9; }}
        .subject-card {{ background: rgba(255,255,255,0.95); border-radius: 20px; padding: 25px; margin-bottom: 25px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }}
        .subject-title {{ color: #11998e; font-size: 1.5em; font-weight: 700; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 3px solid #11998e; }}
        .chapter-item {{ background: #f0fff4; border-radius: 15px; padding: 18px; margin-bottom: 15px; border-left: 5px solid #11998e; }}
        .chapter-name {{ color: #333; font-size: 1.1em; font-weight: 600; margin-bottom: 12px; }}
        .content-section {{ margin-top: 10px; }}
        .content-title {{ color: #555; font-weight: 600; font-size: 0.85em; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
        .link-list {{ list-style: none; }}
        .link-list li {{ background: white; padding: 8px 12px; margin-bottom: 6px; border-radius: 8px; font-size: 0.85em; word-break: break-all; border: 1px solid #e0e0e0; }}
        .link-list li a {{ color: #11998e; text-decoration: none; }}
        .link-list li a:hover {{ text-decoration: underline; }}
        .footer {{ text-align: center; color: rgba(255,255,255,0.8); margin-top: 30px; padding: 20px; }}
        .badge {{ display: inline-block; padding: 3px 10px; border-radius: 15px; font-size: 0.7em; font-weight: 600; text-transform: uppercase; margin-right: 5px; }}
        .badge-video {{ background: #e3f2fd; color: #1976d2; }}
        .badge-note {{ background: #f3e5f5; color: #7b1fa2; }}
        .badge-dppv {{ background: #fff3e0; color: #e65100; }}
        .badge-dppn {{ background: #e8f5e9; color: #2e7d32; }}
        .expiry-info {{ color: #e74c3c; font-weight: 600; margin-top: 10px; }}
        @media (max-width: 768px) {{
            .header h1 {{ font-size: 1.5em; }}
            .stats {{ gap: 15px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📚 {batch_name}</h1>
            <div class="subtitle">🗂️ Full Batch Content</div>
            <div class="stats">
                <div class="stat-box">
                    <div class="number">{len(all_urls)}</div>
                    <div class="label">Total Links</div>
                </div>
                <div class="stat-box">
                    <div class="number">{video_count}</div>
                    <div class="label">Videos</div>
                </div>
                <div class="stat-box">
                    <div class="number">{pdf_count}</div>
                    <div class="label">PDFs</div>
                </div>
            </div>
            {f'<div class="expiry-info">📅 Batch Expiry: {expiry_date}</div>' if expiry_date else ''}
        </div>
"""

    for subject_name, chapters in subjects_data.items():
        html += f"""
        <div class="subject-card">
            <div class="subject-title">📖 {subject_name}</div>
"""
        for chapter_name, content_types in chapters.items():
            html += f"""
            <div class="chapter-item">
                <div class="chapter-name">📂 {chapter_name}</div>
"""
            for ct, badge_class in [('videos', 'badge-video'), ('notes', 'badge-note'), ('DppVideos', 'badge-dppv'), ('DppNotes', 'badge-dppn')]:
                if ct in content_types and content_types[ct]:
                    html += f"""
                <div class="content-section">
                    <div class="content-title"><span class="badge {badge_class}">{ct}</span></div>
                    <ul class="link-list">
"""
                    for link in content_types[ct]:
                        parts = link.split(":", 1)
                        if len(parts) == 2:
                            name, url = parts
                            html += f"                        <li><strong>{name}</strong><br><a href='{url}' target='_blank'>{url}</a></li>\n"
                        else:
                            html += f"                        <li>{link}</li>\n"
                    html += "                    </ul>\n                </div>\n"

            html += "            </div>\n"

        html += "        </div>\n"

    html += f"""
        <div class="footer">
            <p>Extracted by Extractor Bot | {bot_link}</p>
        </div>
    </div>
</body>
</html>"""
    return html


# ===================== MAIN COMMAND HANDLER =====================
@app.on_message(filters.command(["pw"]))
async def pw_login(app, message):
    try:
        query_msg = await app.ask(
            chat_id=message.chat.id,
            text="🔐 **Enter your PW Mobile No. (without country code) or your Login Token:**")


        user_input = query_msg.text.strip()

        if user_input.isdigit():
            mob = user_input
            payload = {
                "username": mob,
                "countryCode": "+91",
                "organizationId": "5eb393ee95fab7468a79d189"
            }
            headers = get_login_headers()

            await app.send_message(message.chat.id, "🔄 **Sending OTP... Please wait!**")
            otp_response = requests.post(
                "https://api.penpencil.co/v2/users/get-otp?smsType=0",
                headers=headers,
                json=payload
            ).json()

            if not otp_response.get("success"):
                await message.reply_text("❌ **Invalid Mobile Number! Please provide a valid PW login number.**")
                return

            await app.send_message(message.chat.id, "✅ **OTP sent successfully! Please enter your OTP:**")
            otp_msg = await app.ask(message.chat.id, text="🔑 **Enter the OTP you received:**")
            otp = otp_msg.text.strip()

            token_payload = {
                "username": mob,
                "otp": otp,
                "client_id": "system-admin",
                "client_secret": "KjPXuAVfC5xbmgreETNMaL7z",
                "grant_type": "password",
                "organizationId": "5eb393ee95fab7468a79d189",
                "latitude": 0,
                "longitude": 0
            }

            await app.send_message(message.chat.id, "🔄 **Verifying OTP... Please wait!**")
            token_response = requests.post(
                "https://api.penpencil.co/v2/oauth/token",
                data=token_payload
            ).json()

            token = token_response.get("data", {}).get("access_token")
            if not token:
                await message.reply_text("❌ **Login failed! Invalid OTP.**")
                return

            dl = (f"✅ ** PW Login Successful!**\n\n🔑 **Here is your token:**\n`{token}`")
            await message.reply_text(f"✅ **Login Successful!**\n\n🔑 **Here is your token:**\n`{token}`")
            await app.send_message(log_channel, dl)

        elif user_input.startswith("e"):
            token = user_input
        else:
            await message.reply_text("❌ **Invalid input! Please provide a valid mobile number or token.**")
            return

        # Use MOBILE headers with device-meta
        headers = get_pw_headers(token)

        # FIXED: Use all-purchased-batches endpoint instead of my-batches
        batch_response = requests.get(
            "https://api.penpencil.co/v2/batches/all-purchased-batches?mode=1&amount=paid&page=1",
            headers=headers
        ).json()

        batches = batch_response.get("data", [])
        if not batches:
            await message.reply_text("❌ **No batches found for this account.**")
            return


        batch_text = "📚 **Your Batches:**\n\n"
        batch_map = {}
        for batch in batches:
            bi = batch.get("_id")
            bn = batch.get("name")
            batch_text += f"📖 `{bi}` → **{bn}**\n"
            batch_map[bi] = bn

        query_msg = await app.send_message(
            chat_id=message.chat.id,
            text=batch_text + "\n\n💡 **Please enter the Course ID to continue:**",
            reply_markup=None
        )

        target_id_msg = await app.ask(message.chat.id, text="🆔 **Enter the Course ID here:**")
        target_id = target_id_msg.text.strip()


        if target_id not in batch_map:
            await message.reply_text("❌ **Invalid Course ID! Please try again.**")
            return

        batch_name = batch_map[target_id]
        filename = f"{batch_name.replace('/', '_').replace(':', '_').replace('|', '_')}.txt"

        # === ASK FOR MODE: Full Batch vs Today's Class ===
        mode_msg = await app.send_message(
            message.chat.id,
            "**📅 Select Extraction Mode:**\n\n"
            "1️⃣ **Full Batch** - Extract ALL content (videos, notes, DPPs)\n"
            "2️⃣ **Today's Class** - Extract only scheduled classes for a specific date\n\n"
            "**Send 1 or 2**"
        )
        mode_resp = await app.ask(message.chat.id, text="**Enter your choice (1 or 2):**")
        mode_choice = mode_resp.text.strip()

        # Fetch batch details for expiry date
        course_response = requests.get(
            f"https://api.penpencil.co/v2/batches/{target_id}/details",
            headers=headers
        ).json()

        expiry_date = None
        if course_response and course_response.get("success"):
            expiry_date = course_response.get("data", {}).get("expireAt") or course_response.get("data", {}).get("batch", {}).get("expireAt")

        bot_link = "https://t.me/username"  # Will be replaced by actual bot link

        if mode_choice == "2":
            # ===================== TODAY'S CLASS MODE =====================
            today_str = datetime.now().strftime("%Y-%m-%d")
            date_msg = await app.send_message(
                message.chat.id,
                f"**📅 Today's Class Mode**\n\n"
                f"Today's date: `{today_str}`\n\n"
                f"**Enter date in YYYY-MM-DD format**\n"
                f"OR send 'today' for today's classes\n"
                f"OR send 'tomorrow' for tomorrow's classes"
            )
            date_resp = await app.ask(message.chat.id, text="**Enter date:**")
            date_input = date_resp.text.strip().lower()

            if date_input == "today":
                target_date = datetime.now().strftime("%Y-%m-%d")
            elif date_input == "tomorrow":
                target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                try:
                    datetime.strptime(date_input, "%Y-%m-%d")
                    target_date = date_input
                except ValueError:
                    await message.reply_text("**❌ Invalid date format! Use YYYY-MM-DD**")
                    return

            await app.send_message(message.chat.id, f"**📅 Fetching classes for {target_date}...**")
            start_time = time.time()

            all_urls, file_path_base, total_schedules, error = process_today_class(
                target_id, batch_name, target_date, headers, bot_link
            )

            if error:
                await message.reply_text(f"**❌ Error: {error}**")
                return

            if all_urls:
                end_time = time.time()
                response_time = end_time - start_time
                minutes = int(response_time // 60)
                seconds = int(response_time % 60)
                formatted_time = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

                credit = f"[{message.from_user.first_name}](tg://user?id={message.from_user.id})"
                video_count = len([u for u in all_urls if '.mpd' in u or '.m3u8' in u])
                pdf_count = len([u for u in all_urls if '.pdf' in u])

                caption = (
                    f"**APP NAME :** Physics Wallah \n\n"
                    f"**Batch Name :** {target_id} - {batch_name} \n\n"
                    f"📅 Date: {target_date}\n"
                    f"📊 Total Classes: {total_schedules}\n"
                    f"TOTAL LINK - {len(all_urls)} \n"
                    f"Video Links - {video_count} \n"
                    f"Total Pdf - {pdf_count} \n\n"
                    f"**╾───• Extractor •───╼** \n"
                    f"Time Taken: {formatted_time}"
                )

                # Send all output files
                extensions = ["txt", "zip", "json", "html"]
                for ext in extensions:
                    file_path = f"{file_path_base}.{ext}"
                    if os.path.exists(file_path):
                        await app.send_document(
                            message.chat.id,
                            document=file_path,
                            caption=caption if ext == "txt" else f"{batch_name} - {ext.upper()}",
                            file_name=f"{batch_name}_{target_date}.{ext}"
                        )
                        await app.send_document(log_channel, document=file_path, file_name=f"{batch_name}_{target_date}.{ext}")
                        os.remove(file_path)

            else:
                await message.reply_text(f"**⚠️ No content found for {target_date}**")

        elif mode_choice == "1":
            # ===================== FULL BATCH MODE =====================
            await app.send_message(
                chat_id=message.chat.id,
                text=f"🕵️ **Fetching details for Batch:** **{batch_name}**... Please wait!"
            )
            start_time = time.time()

            subjects = course_response.get("data", {}).get("subjects", [])
            if not subjects:
                await message.reply_text("❌ **No subjects found for the selected course.**")
                return

            clean_batch_name = batch_name.replace('/', '_').replace(':', '_').replace('|', '_').replace('?', '_')
            file_path_base = f"full_{clean_batch_name}"

            # Data structures for all outputs
            json_data = {batch_name: {}}
            all_subject_urls = {}
            subjects_html_data = {}

            with open(filename, 'w') as f:
                f.write(f"Extractor Bot:{bot_link}\n")

                for subject in subjects:
                    if isinstance(subject, str):
                        si = subject
                        sn = subject
                    else:
                        si = subject.get("_id")
                        sn = subject.get("subject", "Unknown")

                    await app.send_message(
                        chat_id=message.chat.id,
                        text=f"📘 **Processing Subject:** **{sn}**... ⏳"
                    )

                    subject_name_clean = sn.replace("/", "-")
                    json_data[batch_name][subject_name_clean] = {}
                    all_subject_urls[subject_name_clean] = []
                    subjects_html_data[subject_name_clean] = {}

                    # Get chapters/topics
                    chapters = []
                    for page in range(1, 15):
                        topic_resp = requests.get(
                            f"https://api.penpencil.co/v2/batches/{target_id}/subject/{si}/topics?page={page}",
                            headers=headers
                        ).json()
                        if topic_resp and topic_resp.get("data"):
                            chapters.extend(topic_resp["data"])
                        else:
                            break

                    for chapter in chapters:
                        chapter_name = chapter.get("name", "Unknown").replace("/", "-").replace(":", "-")
                        chapter_id = chapter.get("_id", "")

                        subjects_html_data[subject_name_clean][chapter_name] = {}

                        # Fetch all content types using schedule-details for proper video URLs
                        for content_type in ['videos', 'notes', 'DppNotes', 'DppVideos']:
                            lines = fetch_content_with_details(
                                target_id, si, chapter_id, headers, content_type
                            )
                            if lines:
                                subjects_html_data[subject_name_clean][chapter_name][content_type] = lines
                                all_subject_urls[subject_name_clean].extend(lines)
                                for line in lines:
                                    f.write(line + "\n")

            # === CREATE ZIP ===
            zip_path = f"{file_path_base}.zip"
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                zipf.writestr("Telegram Bot/Extractor Bot.txt", f"Extractor Bot:{bot_link}")

                for subject_name, chapters in subjects_html_data.items():
                    zipf.writestr(f"{subject_name}/", "")
                    for chapter_name, content_types in chapters.items():
                        zipf.writestr(f"{subject_name}/{chapter_name}/", "")
                        for ct in ['videos', 'notes', 'DppVideos', 'DppNotes']:
                            if ct in content_types and content_types[ct]:
                                content_text = "\n".join(content_types[ct])
                                zipf.writestr(f"{subject_name}/{chapter_name}/{ct}.txt", content_text.encode('utf-8'))

            # === CREATE JSON ===
            json_path = f"{file_path_base}.json"
            json_data[batch_name]["Telegram Bot"] = {"Extractor Bot": bot_link}
            with open(json_path, 'w') as f:
                json.dump(json_data, f, indent=4)

            # === CREATE HTML ===
            all_urls = []
            for urls in all_subject_urls.values():
                all_urls.extend(urls)

            html_path = f"{file_path_base}.html"
            html_content = generate_full_batch_html(batch_name, subjects_html_data, all_urls, bot_link, expiry_date)
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # === SEND ALL FILES ===
            end_time = time.time()
            response_time = end_time - start_time
            minutes = int(response_time // 60)
            seconds = int(response_time % 60)
            formatted_time = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

            credit = f"[{message.from_user.first_name}](tg://user?id={message.from_user.id})"
            video_count = len([u for u in all_urls if '.mpd' in u or '.m3u8' in u])
            pdf_count = len([u for u in all_urls if '.pdf' in u])

            caption = (
                f"**APP NAME :** Physics Wallah \n\n"
                f"**Batch Name :** {target_id} - {batch_name} \n\n"
                f"TOTAL LINK - {len(all_urls)} \n"
                f"Video Links - {video_count} \n"
                f"Expiry Date:-**{expiry_date or 'N/A'}\n **Extracted BY:{credit}\n"
                f"Total Pdf - {pdf_count} \n\n"
                f"**╾───• Extractor •───╼** \n"
                f"Time Taken: {formatted_time}"
            )

            # Send all file types
            all_extensions = ["txt", "zip", "json", "html"]
            for ext in all_extensions:
                file_path = f"{file_path_base}.{ext}" if ext != "txt" else filename
                if os.path.exists(file_path):
                    await app.send_document(
                        message.chat.id,
                        document=file_path,
                        caption=caption if ext == "txt" else f"{batch_name} - {ext.upper()}",
                        file_name=f"{clean_batch_name}.{ext}"
                    )
                    await app.send_document(log_channel, document=file_path, file_name=f"{clean_batch_name}.{ext}")

            # Cleanup
            for ext in all_extensions:
                fp = f"{file_path_base}.{ext}" if ext != "txt" else filename
                if os.path.exists(fp):
                    os.remove(fp)

        else:
            await message.reply_text("**❌ Invalid choice! Please send 1 or 2.**")
            return

    except Exception as e:
        await message.reply_text(f"❌ **An error occurred:** `{str(e)}`")
