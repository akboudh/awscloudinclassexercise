import os
import json
import boto3
import urllib.parse
from datetime import datetime
import re

s3 = boto3.client('s3')

def inline_md(text: str) -> str:
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    return text

def md_to_html(md: str) -> str:
    lines = md.splitlines()
    html_lines = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()

        # Headings
        m = re.match(r'^(#{1,3})\s+(.*)$', line)
        if m:
            close_list()
            level = len(m.group(1))
            text = m.group(2)
            html_lines.append(f"<h{level}>{inline_md(text)}</h{level}>")
            continue

        # Unordered list
        if re.match(r'^\s*[-*+]\s+', line):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            item = re.sub(r'^\s*[-*+]\s+', '', line)
            html_lines.append(f"<li>{inline_md(item)}</li>")
            continue

        # Blank line
        if line.strip() == "":
            close_list()
            html_lines.append("")
            continue

        # Paragraph
        close_list()
        html_lines.append(f"<p>{inline_md(line)}</p>")

    close_list()

    body = "\n".join(html_lines)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Note</title></head>
<body>
<div style='color:#666;font-size:small'>Generated: {datetime.utcnow().isoformat()}Z</div>
{body}
</body></html>"""

def update_index(bucket: str):
    objs = s3.list_objects_v2(Bucket=bucket)
    items = []
    for obj in objs.get('Contents', []):
        key = obj['Key']
        if key.endswith(".html") and key != "index.html":
            items.append(key)
    items.sort()
    lis = "\n".join(f'<li><a href="{k}">{k}</a></li>' for k in items)
    html = f"<html><body><h1>Notes</h1><ul>{lis}</ul></body></html>"
    s3.put_object(Bucket=bucket, Key="index.html", Body=html.encode("utf-8"), ContentType="text/html")

def handler(event, context):
    for record in event.get("Records", []):
        src_bucket = record["s3"]["bucket"]["name"]
        src_key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        if not src_key.lower().endswith(".md"):
            continue

        # Read Markdown
        obj = s3.get_object(Bucket=src_bucket, Key=src_key)
        md = obj["Body"].read().decode("utf-8")

        # Convert
        html = md_to_html(md)

        # Prefer explicit OUTPUT_BUCKET; else try -in -> -out; else fallback
        dst_bucket = os.environ.get("OUTPUT_BUCKET")
        if not dst_bucket:
            if src_bucket.endswith("-in"):
                dst_bucket = src_bucket.replace("-in", "-out", 1)
            else:
                dst_bucket = src_bucket  # fallback

        # Same key, .html extension
        dst_key = src_key.rsplit(".", 1)[0] + ".html"

        # Write HTML
        s3.put_object(
            Bucket=dst_bucket,
            Key=dst_key,
            Body=html.encode("utf-8"),
            ContentType="text/html"
        )

        # Update index in destination
        update_index(dst_bucket)

    return {"status": "ok"}
