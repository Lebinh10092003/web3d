import json
import urllib.parse
import urllib.request


def fetch_playlist_items(playlist_id, api_key):
    if not playlist_id or not api_key:
        return []
    items = []
    page_token = ""
    base_url = "https://www.googleapis.com/youtube/v3/playlistItems"
    while True:
        params = {
            "part": "snippet",
            "maxResults": 50,
            "playlistId": playlist_id,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return items
        for entry in payload.get("items", []):
            snippet = entry.get("snippet") or {}
            title = (snippet.get("title") or "").strip()
            resource = snippet.get("resourceId") or {}
            video_id = (resource.get("videoId") or "").strip()
            if not video_id:
                continue
            if title.lower() in {"private video", "deleted video"}:
                continue
            items.append({"title": title, "video_id": video_id})
        page_token = payload.get("nextPageToken") or ""
        if not page_token:
            break
    return items
