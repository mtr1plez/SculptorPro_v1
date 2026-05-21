"""
YouTube Trends Router — Viral Video Discovery
Uses YouTube Data API v3 to find trending & viral videos.
"""

import os
import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import json
import random
from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
import httpx

from src.utils.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

router = APIRouter()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def _get_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key or key == "your_youtube_api_key_here":
        raise HTTPException(
            status_code=503,
            detail="YouTube API key not configured. Add YOUTUBE_API_KEY to your .env file."
        )
    return key


def _calculate_virality(view_count: int, like_count: int, comment_count: int, published_at: str) -> dict:
    """
    Calculate virality score based on view velocity and engagement.
    
    Key insight: a video that got 1M views in 3 days is WAY more viral
    than one that got 1M views in a year.
    """
    try:
        pub_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pub_date = datetime.now(timezone.utc) - timedelta(days=30)

    now = datetime.now(timezone.utc)
    delta = (now - pub_date).total_seconds() / 86400  # days
    days_alive = max(delta, 0.04)  # ~1 hour minimum to avoid insane spikes

    # === Core Metrics ===
    views_per_day = view_count / days_alive
    views_per_hour = view_count / max(days_alive * 24, 1)

    # Engagement rate (likes + weighted comments vs views)
    engagement_rate = (like_count + comment_count * 3) / max(view_count, 1)

    # === Virality Score (0–100 log scale) ===
    # 10 views/day = ~15, 1K/day = ~45, 100K/day = ~75, 10M/day = ~100
    if views_per_day > 0:
        raw_score = math.log10(views_per_day) * 15
    else:
        raw_score = 0

    # Boost by engagement (max 1.5x multiplier)
    engagement_boost = 1 + min(engagement_rate * 10, 0.5)
    virality_score = min(round(raw_score * engagement_boost, 1), 100)
    virality_score = max(virality_score, 0)

    # === Category ===
    if virality_score >= 80:
        badge = "🔥"
        label = "Mega Viral"
        color = "#ef4444"  # red
    elif virality_score >= 60:
        badge = "⚡"
        label = "Viral"
        color = "#f97316"  # orange
    elif virality_score >= 40:
        badge = "📈"
        label = "Trending"
        color = "#eab308"  # yellow
    elif virality_score >= 20:
        badge = "📊"
        label = "Growing"
        color = "#3b82f6"  # blue
    else:
        badge = "🐢"
        label = "Slow"
        color = "#6b7280"  # gray

    # Human-readable velocity
    if views_per_day >= 1_000_000:
        velocity_text = f"{views_per_day / 1_000_000:.1f}M views/day"
    elif views_per_day >= 1_000:
        velocity_text = f"{views_per_day / 1_000:.1f}K views/day"
    else:
        velocity_text = f"{int(views_per_day)} views/day"

    # Human-readable age
    if days_alive < 1:
        age_text = f"{int(days_alive * 24)}h ago"
    elif days_alive < 30:
        age_text = f"{int(days_alive)}d ago"
    elif days_alive < 365:
        age_text = f"{int(days_alive / 30)}mo ago"
    else:
        age_text = f"{days_alive / 365:.1f}y ago"

    return {
        "score": virality_score,
        "badge": badge,
        "label": label,
        "color": color,
        "views_per_day": round(views_per_day),
        "views_per_hour": round(views_per_hour),
        "velocity_text": velocity_text,
        "engagement_rate": round(engagement_rate * 100, 2),
        "days_alive": round(days_alive, 1),
        "age_text": age_text,
    }


def _parse_video_item(item: dict, stats: dict = None) -> dict:
    """Parse a YouTube API video item into our format."""
    snippet = item.get("snippet", {})
    video_id = item.get("id", "")
    
    # Handle search results where id is an object
    if isinstance(video_id, dict):
        video_id = video_id.get("videoId", "")
    
    statistics = stats or item.get("statistics", {})
    
    view_count = int(statistics.get("viewCount", 0))
    like_count = int(statistics.get("likeCount", 0))
    comment_count = int(statistics.get("commentCount", 0))
    published_at = snippet.get("publishedAt", "")
    
    # Best thumbnail
    thumbnails = snippet.get("thumbnails", {})
    thumb = (
        thumbnails.get("maxres", {}).get("url") or
        thumbnails.get("high", {}).get("url") or
        thumbnails.get("medium", {}).get("url") or
        thumbnails.get("default", {}).get("url", "")
    )
    
    virality = _calculate_virality(view_count, like_count, comment_count, published_at)
    
    return {
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "channel": snippet.get("channelTitle", ""),
        "channel_id": snippet.get("channelId", ""),
        "description": snippet.get("description", "")[:300],
        "thumbnail": thumb,
        "published_at": published_at,
        "category_id": snippet.get("categoryId", ""),
        "stats": {
            "views": view_count,
            "likes": like_count,
            "comments": comment_count,
        },
        "virality": virality,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


# ============================================================
#  AI NICHE ANALYSIS
# ============================================================

class VideoContext(BaseModel):
    title: str
    channel: str
    views: int
    published_at: str
    virality_score: float

class AnalyzeNichesRequest(BaseModel):
    videos: List[VideoContext]

@router.post("/analyze-niches")
async def analyze_niches(req: AnalyzeNichesRequest):
    """
    Analyzes a list of trending videos and extracts micro-niches
    and actionable feedback using Gemini.
    """
    if not req.videos:
        raise HTTPException(status_code=400, detail="No videos provided for analysis.")
        
    prompt = f"""
You are an elite YouTube Strategist and Niche Analyst.
I will give you a list of {len(req.videos)} currently highly viral or trending YouTube videos.

Your task is to group them into distinct, actionable "micro-niches" that a content creator could start today. 
Analyze WHY they are going viral, assess the difficulty, and suggest how to monetize.

Video Data:
"""
    for v in req.videos[:50]: # Limits to top 50 to save context
        prompt += f"- Title: {v.title}\n  Channel: {v.channel} | Views: {v.views} | Virality Score: {v.virality_score}\n"

    prompt += """
Respond strictly in valid JSON format with the following structure:
{
  "niches": [
    {
      "name": "Catchy name of the micro-niche",
      "hook_secret": "Deep analysis of why this format works psychologically",
      "faceless": true/false,
      "difficulty": "Low" | "Medium" | "High",
      "monetization": "How to make money from this (e.g., sponsorships, digital products)",
      "ideas": ["Idea 1", "Idea 2", "Idea 3"]
    }
  ]
}
Make sure to extract 3 to 5 strong niches. Be specific and insightful, not generic.
"""

    gemini = GeminiClient()
    try:
        # Use simple text generation for now.
        response = gemini.generate_content(prompt)
        text = response.text
        # Clean JSON markdown if present
        clean_json = gemini.parse_json(text)
        data = json.loads(clean_json)
        return data
    except Exception as e:
        logger.error(f"Error analyzing niches: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _enrich_with_channel_stats(videos: List[dict], api_key: str) -> List[dict]:
    """Fetches channel subscriber counts and calculates outlier ratios."""
    if not videos:
        return videos
        
    channel_ids = list(set([v["channel_id"] for v in videos if v.get("channel_id")]))
    if not channel_ids:
        return videos
        
    # YouTube API allows up to 50 IDs per request
    channel_stats = {}
    
    # Chunk IDs just in case, although videos list is max 50
    for i in range(0, len(channel_ids), 50):
        chunk = channel_ids[i:i+50]
        params = {
            "part": "statistics",
            "id": ",".join(chunk),
            "key": api_key
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{YOUTUBE_API_BASE}/channels", params=params)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    cid = item["id"]
                    subs_str = item.get("statistics", {}).get("subscriberCount", "0")
                    hidden = item.get("statistics", {}).get("hiddenSubscriberCount", False)
                    # If hidden, treat as a large number so it doesn't trigger fake outlier
                    subs = int(subs_str) if not hidden and subs_str.isdigit() else 999999999
                    channel_stats[cid] = subs

    for v in videos:
        subs = channel_stats.get(v.get("channel_id"), 999999999)
        v["channel_stats"] = {"subscribers": subs}
        
        # Calculate Outlier Ratio (Views / Subscribers)
        # Avoid division by zero
        safe_subs = max(subs, 1)
        ratio = v["stats"]["views"] / safe_subs
        v["virality"]["outlier_ratio"] = round(ratio, 1)
        
    return videos

# ============================================================
#  ENDPOINTS
# ============================================================

@router.get("/trending")
async def get_trending(
    region: str = Query("US", description="ISO 3166-1 alpha-2 country code"),
    category: Optional[str] = Query("0", description="YouTube Video Category ID"),
    max_results: int = Query(24, ge=1, le=50),
    outliers_only: bool = Query(False, description="Filter for outlier videos only")
):
    """
    Get currently trending videos from YouTube's mostPopular chart.
    Cost: 1 API unit per call (cheap!).
    """
    api_key = _get_api_key()
    
    # Fetch max 50 from YouTube to allow varied sampling
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": 50,
        "key": api_key,
    }
    if category and category != "0":
        params["videoCategoryId"] = category
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{YOUTUBE_API_BASE}/videos", params=params)
    
    if resp.status_code != 200:
        error_detail = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(status_code=resp.status_code, detail=f"YouTube API error: {error_detail}")
    
    data = resp.json()
    videos = []
    for item in data.get("items", []):
        parsed = _parse_video_item(item)
        videos.append(parsed)
        
    # Enrich with subscriber counts and calculate outlier ratios
    videos = await _enrich_with_channel_stats(videos, api_key)

    # Filter for outliers if requested (Ratio >= 3)
    if outliers_only:
        videos = [v for v in videos if v.get("virality", {}).get("outlier_ratio", 0) >= 3.0]
    
    # Sort by virality score (highest first)
    videos.sort(key=lambda v: v["virality"]["score"], reverse=True)
    
    # Randomly select requested number from the top pool for variety
    if len(videos) > max_results:
        # Take the top N pool and pick max_results from it to keep quality but ensure variety
        pool_size = min(len(videos), max(max_results * 2, 30))
        top_pool = videos[:pool_size]
        videos = random.sample(top_pool, max_results)
        videos.sort(key=lambda v: v["virality"]["score"], reverse=True)

    return {
        "videos": videos,
        "total": len(videos),
        "region": region,
        "source": "trending",
    }


@router.get("/search")
async def search_videos(
    q: str = Query(..., description="Search keywords"),
    region: str = Query("US", description="ISO 3166-1 alpha-2 country code"),
    category: str = Query("0", description="YouTube video category ID"),
    period: str = Query("week", description="Time period: today, week, month, year, custom"),
    date_from: Optional[str] = Query(None, description="Custom start date (ISO 8601)"),
    date_to: Optional[str] = Query(None, description="Custom end date (ISO 8601)"),
    sort_by: str = Query("virality", description="Sort: virality, views, date, relevance"),
    max_results: int = Query(24, ge=1, le=50),
    outliers_only: bool = Query(False, description="Filter for outlier videos only")
):
    """
    Search for trending/viral content using keywords and specific ranking parameters.
    Cost: 100 units (search) + 1 unit (video details) = 101 units per call.
    """
    api_key = _get_api_key()
    
    # Determine date range
    now = datetime.now(timezone.utc)
    if period == "today":
        published_after = (now - timedelta(days=1)).isoformat()
    elif period == "week":
        published_after = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        published_after = (now - timedelta(days=30)).isoformat()
    elif period == "year":
        published_after = (now - timedelta(days=365)).isoformat()
    elif period == "custom" and date_from:
        published_after = date_from
    else:
        published_after = (now - timedelta(days=7)).isoformat()
    
    published_before = None
    if period == "custom" and date_to:
        published_before = date_to
    
    # YouTube sort mapping (for initial search)
    yt_order = "relevance"
    if sort_by == "views":
        yt_order = "viewCount"
    elif sort_by == "date":
        yt_order = "date"
    
    # Step 1: Search for video IDs (fetch 50 to allow sampling)
    search_params = {
        "part": "snippet",
        "q": q,
        "type": "video",
        "regionCode": region,
        "order": yt_order,
        "maxResults": 50,
        "publishedAfter": published_after,
        "key": api_key,
    }
    if published_before:
        search_params["publishedBefore"] = published_before
    if category and category != "0":
        search_params["videoCategoryId"] = category
    
    async with httpx.AsyncClient(timeout=15) as client:
        search_resp = await client.get(f"{YOUTUBE_API_BASE}/search", params=search_params)
    
    if search_resp.status_code != 200:
        error_detail = search_resp.json().get("error", {}).get("message", search_resp.text)
        raise HTTPException(status_code=search_resp.status_code, detail=f"YouTube API error: {error_detail}")
    
    search_data = search_resp.json()
    search_items = search_data.get("items", [])
    
    if not search_items:
        return {"videos": [], "total": 0, "query": q, "source": "search"}
    
    # Step 2: Get full statistics for found videos
    video_ids = [
        item["id"]["videoId"]
        for item in search_items
        if item.get("id", {}).get("videoId")
    ]
    
    if not video_ids:
        return {"videos": [], "total": 0, "query": q, "source": "search"}
    
    stats_params = {
        "part": "snippet,statistics",
        "id": ",".join(video_ids),
        "key": api_key,
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        stats_resp = await client.get(f"{YOUTUBE_API_BASE}/videos", params=stats_params)
    
    if stats_resp.status_code != 200:
        # Fallback: return search results without stats
        logger.warning("Failed to fetch video stats, returning search results only")
        videos = []
        for item in search_items:
            parsed = _parse_video_item(item)
            videos.append(parsed)
        return {"videos": videos, "total": len(videos), "query": q, "source": "search"}
    
    stats_data = stats_resp.json()
    videos = []
    for item in stats_data.get("items", []):
        parsed = _parse_video_item(item)
        videos.append(parsed)
        
    # Enrich with subscriber counts and calculate outlier ratios
    videos = await _enrich_with_channel_stats(videos, api_key)

    # Filter for outliers if requested
    if outliers_only:
        videos = [v for v in videos if v.get("virality", {}).get("outlier_ratio", 0) >= 3.0]
    
    # Add variance sampling
    if len(videos) > max_results:
        pool_size = min(len(videos), max(max_results * 2, 30))
        # Keep top half of pool highly relevant, then sample
        pool = videos[:pool_size]
        videos = random.sample(pool, max_results)

    # Re-sort by user request after sampling
    if sort_by == "virality":
        videos.sort(key=lambda v: v["virality"]["score"], reverse=True)
    elif sort_by == "views":
        videos.sort(key=lambda v: v["stats"]["views"], reverse=True)
    elif sort_by == "date":
        videos.sort(key=lambda v: v["published_at"], reverse=True)
    
    return {
        "videos": videos,
        "total": len(videos),
        "query": q,
        "period": period,
        "region": region,
        "source": "search",
        "next_page_token": search_data.get("nextPageToken"),
    }


@router.get("/video/{video_id}")
async def get_video_details(video_id: str):
    """
    Get detailed stats and virality score for a single video.
    Cost: 1 API unit.
    """
    api_key = _get_api_key()
    
    params = {
        "part": "snippet,statistics,contentDetails",
        "id": video_id,
        "key": api_key,
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{YOUTUBE_API_BASE}/videos", params=params)
    
    if resp.status_code != 200:
        error_detail = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(status_code=resp.status_code, detail=error_detail)
    
    data = resp.json()
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail="Video not found")
    
    item = items[0]
    parsed = _parse_video_item(item)
    
    # Add duration from contentDetails
    content_details = item.get("contentDetails", {})
    parsed["duration"] = content_details.get("duration", "")
    parsed["definition"] = content_details.get("definition", "")
    
    return parsed


@router.get("/categories")
async def get_categories(
    region: str = Query("US", description="ISO 3166-1 alpha-2 country code"),
):
    """
    Get available YouTube video categories for a region.
    Cost: 1 API unit.
    """
    api_key = _get_api_key()
    
    params = {
        "part": "snippet",
        "regionCode": region,
        "key": api_key,
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{YOUTUBE_API_BASE}/videoCategories", params=params)
    
    if resp.status_code != 200:
        error_detail = resp.json().get("error", {}).get("message", resp.text)
        raise HTTPException(status_code=resp.status_code, detail=error_detail)
    
    data = resp.json()
    categories = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        if snippet.get("assignable", False):
            categories.append({
                "id": item["id"],
                "title": snippet["title"],
            })
    
    return {"categories": categories, "region": region}
