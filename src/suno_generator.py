import time
import json
import logging
from typing import Dict, Optional, Tuple, List
from curl_cffi import requests

logger = logging.getLogger(__name__)

class SunoClient:
    def __init__(self, cookies: Dict[str, str]):
        self.session = requests.Session(impersonate="chrome120")
        
        # Build cookie string
        cookie_str = cookies.get("__cookie_header") if isinstance(cookies, dict) else None
        if not cookie_str:
            cookie_parts = []
            for name, value in cookies.items():
                if name.startswith("__cookie_"):
                    continue
                cookie_parts.append(f"{name}={value}")
            cookie_str = "; ".join(cookie_parts)
        
        # Suno requires auth token which is the Clerk session
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/",
            "Cookie": cookie_str
        })
        logger.info(
            "Suno auth cookie names: %s",
            ", ".join([part.split("=", 1)[0] for part in cookie_str.split("; ") if part])
        )
        self.base_url = "https://studio-api.suno.ai/api"  # old URL that points to Render custom domain, suspended
        # Override to current official API URL
        self.base_url = "https://studio-api.prod.suno.com/api"
        
        # We need to fetch the real short-lived JWT from Clerk using the cookies
        self._set_auth_token(cookies)

    def _mask_id(self, value: Optional[str]) -> str:
        if not value:
            return ""
        if len(value) <= 12:
            return value[:4] + "..."
        return f"{value[:8]}...{value[-4:]}"

    def _find_session_ids_recursive(self, value) -> List[str]:
        found = []

        if isinstance(value, str):
            if value.startswith("sess_"):
                found.append(value)
            return found

        if isinstance(value, dict):
            object_type = value.get("object") or value.get("__typename") or value.get("type")
            for key in ("id", "session_id", "sid", "last_active_session_id"):
                candidate = value.get(key)
                if isinstance(candidate, str) and (
                    candidate.startswith("sess_")
                    or key == "last_active_session_id"
                    or object_type == "session"
                ):
                    found.append(candidate)

            for nested in value.values():
                found.extend(self._find_session_ids_recursive(nested))
            return found

        if isinstance(value, list):
            for item in value:
                found.extend(self._find_session_ids_recursive(item))
            return found

        return found

    def _extract_session_id(self, response_data) -> Optional[str]:
        """Clerk has changed the client payload shape several times."""
        if not isinstance(response_data, dict):
            return None

        direct_sid = response_data.get("last_active_session_id") or response_data.get("session_id")
        if isinstance(direct_sid, str) and direct_sid:
            return direct_sid

        sessions = response_data.get("sessions") or []
        if isinstance(sessions, dict):
            sessions = list(sessions.values())
        if not isinstance(sessions, list):
            return None

        candidates = []
        for item in sessions:
            if isinstance(item, str) and item:
                candidates.append({"id": item, "status": "unknown"})
                continue

            if not isinstance(item, dict):
                continue

            nested_session = item.get("session")
            if isinstance(nested_session, dict):
                item = {**nested_session, **item}

            sid = item.get("id") or item.get("session_id") or item.get("sid")
            if isinstance(sid, str) and sid:
                candidates.append({
                    "id": sid,
                    "status": item.get("status") or item.get("state") or "unknown"
                })

        for candidate in candidates:
            if candidate.get("status") == "active":
                logger.info(f"Found active session in sessions payload: {self._mask_id(candidate['id'])}")
                return candidate["id"]

        if candidates:
            logger.info(f"Using first session from sessions payload: {self._mask_id(candidates[0]['id'])} (status: {candidates[0].get('status')})")
            return candidates[0]["id"]

        recursive_ids = []
        seen = set()
        for sid in self._find_session_ids_recursive(response_data):
            if sid not in seen:
                recursive_ids.append(sid)
                seen.add(sid)

        if recursive_ids:
            logger.info(f"Found Clerk session recursively: {self._mask_id(recursive_ids[0])}")
            return recursive_ids[0]

        return None

    def _set_auth_token(self, cookies: Dict[str, str]):
        """Fetches the actual Bearer token from Clerk using the session cookies."""
        # Try multiple Clerk JS versions in case one is stale
        clerk_versions = ["5.56.0", "5.18.0", "5.35.0"]
        
        for clerk_js_ver in clerk_versions:
            try:
                clerk_url = f"https://clerk.suno.com/v1/client?_clerk_js_version={clerk_js_ver}"
                resp = self.session.get(clerk_url)
                
                if resp.status_code != 200:
                    logger.warning(f"Clerk client response status {resp.status_code} (version {clerk_js_ver})")
                    continue
                    
                data = resp.json()
                response_data = data.get("response", data)  # Some versions wrap in "response"
                
                # Log structure for debugging
                logger.info(f"Clerk response keys: {list(response_data.keys()) if isinstance(response_data, dict) else type(response_data)}")
                if isinstance(response_data, dict):
                    sessions = response_data.get("sessions")
                    if isinstance(sessions, list):
                        logger.info(f"Clerk sessions payload length: {len(sessions)}")
                    elif sessions is not None:
                        logger.info(f"Clerk sessions payload type: {type(sessions).__name__}")
                
                sid = self._extract_session_id(response_data)
                
                if not sid:
                    logger.warning(f"No session ID found in Clerk response (version {clerk_js_ver}). Keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'N/A'}")
                    continue
                
                # Fetch fresh JWT token
                token_url = f"https://clerk.suno.com/v1/client/sessions/{sid}/tokens?_clerk_js_version={clerk_js_ver}"
                token_resp = self.session.post(token_url)
                
                if token_resp.status_code != 200:
                    logger.warning(f"Clerk /tokens status {token_resp.status_code} for session {self._mask_id(sid)}")
                    continue
                    
                token_data = token_resp.json()
                token_response = token_data.get("response", token_data) if isinstance(token_data, dict) else {}
                jwt = token_response.get("jwt") if isinstance(token_response, dict) else None
                if jwt:
                    self.session.headers.update({
                        "Authorization": f"Bearer {jwt}"
                    })
                    # The broad login cookie bundle is only needed for Clerk token exchange.
                    # Sending it to studio-api can exceed header limits and can also confuse
                    # Suno's token validation when duplicate auth cookies are present.
                    self.session.headers.pop("Cookie", None)
                    logger.info("✅ Successfully loaded and refreshed Suno JWT token via Clerk.")
                    return
                else:
                    logger.warning(f"Clerk /tokens returned 200 but no 'jwt' key. Response keys: {list(token_data.keys()) if isinstance(token_data, dict) else type(token_data)}")
                    
            except Exception as e:
                logger.error(f"Error fetching Clerk token (version {clerk_js_ver}): {e}")
        
        # All attempts failed — raise explicitly
        logger.error("❌ All Clerk JWT fetch attempts failed. Cookies may be expired or invalid.")
        raise Exception(
            "Failed to authenticate with Suno. Please try logging in again. "
            "The authentication cookies may have expired."
        )

    def generate(self, tags: str, prompt: str = "", make_instrumental: bool = True) -> List[str]:
        """
        Submits a generation request to Suno. Returns a list of clip IDs.
        """
        url = f"{self.base_url}/generate/v2/"
        payload = {
            "prompt": prompt,
            "tags": tags,
            "make_instrumental": make_instrumental,
            "mv": "chirp-v3-5" # Model version
        }
        
        logger.info(f"Suno generation payload: {payload}")
        response = self.session.post(url, json=payload)
        
        if response.status_code != 200:
            logger.error(f"Suno generate error {response.status_code}: {response.text}")
            raise Exception(f"Failed to generate music: {response.text}")
            
        data = response.json()
        clip_ids = [clip["id"] for clip in data.get("clips", []) if "id" in clip]
        
        if not clip_ids:
            # Fallback if the response changes
            if "id" in data:
               clip_ids = [data["id"]]
            else:
               raise Exception("No clip IDs returned from Suno API.")
               
        return clip_ids

    def poll(self, clip_ids: List[str], timeout: int = 180) -> Tuple[str, str]:
        """
        Polls until at least one clip is ready. Returns (status, audio_url).
        """
        if not clip_ids:
            return "error", ""
            
        url = f"{self.base_url}/feed/?ids={','.join(clip_ids)}"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = self.session.get(url)
                if response.status_code == 200:
                    data = response.json()
                    
                    for clip in data:
                        status = clip.get("status")
                        audio_url = clip.get("audio_url")
                        
                        if status == "streaming" or status == "complete":
                            if audio_url:
                                return "complete", audio_url
                        elif status == "error":
                            logger.error(f"Suno generating error for clip {clip.get('id')}")
                            # Keep checking other clips if one failed
                
                # Sleep before polling again
                time.sleep(5)
            except Exception as e:
                logger.error(f"Error polling Suno API: {e}")
                time.sleep(5)
                
        return "timeout", ""

    def download(self, audio_url: str, save_path: str) -> bool:
        """
        Downloads the generated MP3 file.
        """
        try:
            response = self.session.get(audio_url, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                return True
            else:
                logger.error(f"Failed to download audio. Status: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Exception during audio download: {e}")
            return False
