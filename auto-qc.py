import os
import time
import json
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types 
from playwright.sync_api import sync_playwright
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv
import PIL.Image
import io

# ==========================================
# --- 1. CONFIGURATION ---
# ==========================================

# Sitemap Settings
USE_URL = False  # Set to False to use the local file
SITEMAP_URL = "https://example.com.my/sitemap.xml" 
SITEMAP_FILE = "AseanGems_Sitemap.xml"

# Google Sheets Settings
GOOGLE_SHEET_TAB_NAME = "CountryView" # Matches your exact tab name in Google Sheets

# AI Model Settings (Free Tier and Support Vision Models)
# gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3.1-flash-lite-preview
GEMINI_MODEL = "gemini-3.1-flash-lite-preview"
COOLDOWN_SECONDS = 15 # Seconds to wait between pages to respect API limits


# Local Storage Settings
SAVE_LOCAL_SCREENSHOTS = True # Set to False for "No-Trace" runs (to save storage/time)
SCREENSHOT_DIR = "audit_screenshots"

# Browser Settings
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080

# ==========================================
# --- 2. SETUP & AUTH ---
# ==========================================
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_KEY)

SERVICE_ACCOUNT_FILE = 'credentials.json'
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)

# ==========================================
# --- 3. GOOGLE SHEETS FUNCTIONS ---
# ==========================================
def update_sheet(row_data):
    """Appends audit results to the Google Sheet."""
    body = {'values': [row_data]}
    try:
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{GOOGLE_SHEET_TAB_NAME}!A:E",
            valueInputOption="RAW",
            body=body
        ).execute()
    except Exception as e:
        print(f"Sheets Error: {e}")

def check_needs_header():
    """Checks if the Google Sheet is empty to prevent duplicate headers."""
    try:
        # We only need to check the very first cell (A1)
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{GOOGLE_SHEET_TAB_NAME}!A1:A1" 
        ).execute()
        
        # If 'values' doesn't exist in the result, the cell is empty
        return not result.get('values') 
    except Exception as e:
        print(f"Header Check Error: {e}")
        return False

def get_audited_urls():
    """Fetches the list of URLs already audited from the Google Sheet."""
    print("Checking Google Sheet for previously audited URLs...")
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{GOOGLE_SHEET_TAB_NAME}!B:B"
        ).execute()
        
        rows = result.get('values', [])
        audited_urls = {row[0].strip() for row in rows if row and row[0].strip() != "URL"}
        return audited_urls
        
    except Exception as e:
        print(f"Error reading from Google Sheet: {e}")
        return set()

# ==========================================
# --- 4. SITEMAP PARSING FUNCTIONS ---
# ==========================================
def get_urls_from_web(url):
    """Recursively fetches URLs and filters for actual pages only."""
    all_pages = []
    exclude_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.pdf', '.zip', '.mp4')
    
    try:
        print(f"Scanning sitemap: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'xml')
        
        found_links = [loc.text for loc in soup.find_all('loc')]
        
        for link in found_links:
            if link.endswith('.xml') and link != url:
                all_pages.extend(get_urls_from_web(link))
            elif not any(link.lower().endswith(ext) for ext in exclude_extensions):
                all_pages.append(link)
        
        return list(set(all_pages)) 

    except Exception as e:
        print(f"Error scanning {url}: {e}")
        return all_pages

def get_urls_from_file(file_path):
    """Parses a local XML sitemap file for URLs, excluding media files."""
    exclude_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.pdf', '.zip', '.mp4')
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            
        soup = BeautifulSoup(content, 'xml')
        
        raw_urls = [loc.text for loc in soup.find_all('loc')]
        
        filtered_urls = [
            url for url in raw_urls
            if not any(url.lower().endswith(ext) for ext in exclude_extensions)
        ]
        
        print(f"Successfully loaded {len(filtered_urls)} valid page URLs from {file_path} (Ignored {len(raw_urls) - len(filtered_urls)} media/file URLs).")
        return filtered_urls
        
    except Exception as e:
        print(f"Error reading sitemap file: {e}")
        return []

# ==========================================
# --- 5. VISION & FUNCTIONAL AUDIT ---
# ==========================================
def run_audit():
    if USE_URL:
        urls = get_urls_from_web(SITEMAP_URL)
    else:
        urls = get_urls_from_file(SITEMAP_FILE)

    if not urls:
        print("No URLs found. Check your source settings.")
        return
    
    audited_urls = get_audited_urls()
    pending_urls = [u for u in urls if u not in audited_urls]
    
    print("\n" + "="*60)
    print(f"SITEMAP SCAN COMPLETE: Found {len(urls)} total URLs.")
    print(f"SKIPPED: {len(urls) - len(pending_urls)} URLs already audited in Google Sheets.")
    print(f"PENDING AUDIT: {len(pending_urls)} URLs remaining in the queue.")
    print("="*60)
    
    if not pending_urls:
        print("\nAll URLs in the sitemap have already been audited! Exiting script.")
        return
    
    for i, u in enumerate(sorted(pending_urls)): 
        print(f"[{i+1}] {u}")
    
    confirm = input(f"\nProceed to audit {len(pending_urls)} pending pages? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("Audit aborted. No API credits used.")
        return
    
    print("\nInitializing Browser and starting audit...")
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False, 
            channel="chrome", 
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
                  ]
        )
        context = browser.new_context(
            viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            }
        )
        page = context.new_page()
        
        # Only write the header row if the sheet is completely empty
        if check_needs_header():
            print("Sheet is empty. Writing header row...")
            update_sheet(["Page Name", "URL", "Issues", "Suggestions", "Timestamp"])
        
        for url in pending_urls:
            print(f"\nAuditing: {url}")
            try:
                # ==========================================
                # PHASE 1: INITIAL LOAD & CLOUDFLARE BYPASS
                # ==========================================
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000) 
                except Exception as load_err:
                    print(f"Warning: Page load hung up, but attempting to proceed... ({load_err})")

                # The Cloudflare Bouncer: Wait for challenge screens to automatically resolve
                for _ in range(15):
                    current_title = page.title().lower()
                    if "moment" in current_title or "cloudflare" in current_title or "attention required" in current_title:
                        print("🛡️ Cloudflare challenge detected. Waiting 2 seconds for auto-resolve...")
                        page.wait_for_timeout(2000)
                    else:
                        break

                page_name = page.title()
                if not page_name or "moment" in page_name.lower():
                    page_name = "Unknown Page (Or Blocked)"

                # ==========================================
                # PHASE 2: DEEP SCROLL & ASSET LOADING
                # ==========================================
                print("Deep scrolling and forcing lazy-loaded Elementor/JetEngine assets...")
                page.evaluate("""
                    async () => {
                        // 1. THE HUMAN SCROLL: Trigger Intersection Observers
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 400; 
                            const timer = setInterval(() => {
                                const scrollHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                
                                // Dispatch real scroll events to wake up stubborn plugins like JetEngine
                                window.dispatchEvent(new window.Event('scroll'));

                                if (totalHeight >= scrollHeight - window.innerHeight) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 300); 
                        });

                        // 2. ASSET LOCK: Wait for Custom Fonts, Images, and Videos
                        await document.fonts.ready;

                        const images = Array.from(document.querySelectorAll('img'));
                        
                        images.forEach(img => {
                            img.removeAttribute('loading'); 
                            const realSrc = img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || img.getAttribute('data-srcset');
                            if (realSrc && !img.src.includes(realSrc)) {
                                img.setAttribute('src', realSrc);
                            }
                        });

                        await Promise.all(images.map(async (img) => {
                            // If the image is already painted and real, move on instantly
                            if (img.complete && img.naturalHeight > 1) return;
                            
                            try {
                                // Listen strictly for the browser to finish downloading and decoding the image
                                await img.decode();
                            } catch (error) {
                                // If the image link is a 404 or broken, decode() throws an error.
                                // We catch it silently here so the script doesn't crash and just skips the broken image.
                                return;
                            }
                        }));

                        const media = Array.from(document.querySelectorAll('video, iframe'));
                        await Promise.all(media.map(m => {
                            if (m.readyState >= 3) return Promise.resolve();
                            return new Promise(res => { 
                                const t = setTimeout(res, 5000); // 5 sec max wait for broken videos
                                m.onloadeddata = () => { clearTimeout(t); res(); };
                                m.onload = () => { clearTimeout(t); res(); };
                                m.onerror = () => { clearTimeout(t); res(); };
                            });
                        }));
                    }
                """)

                # ==========================================
                # PHASE 3: NETWORK SETTLEMENT
                # ==========================================
                # Wait for JetEngine's AJAX network traffic to stop
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except:
                    print("Network didn't fully idle. Moving to final UI settlement...")

                # Final pause for grids to populate
                page.wait_for_timeout(3000)

                print("Returning to top of page to reset sticky headers...")
                page.evaluate("""() => {
                    window.scrollTo(0, 0);
                    // Dispatch a scroll event so the website's JavaScript notices we moved
                    window.dispatchEvent(new window.Event('scroll')); 
                }""")

                page.wait_for_timeout(2000)

                # ==========================================
                # PHASE 4: DOM PREP, WIDTH FIX & EXTRACTION
                # ==========================================
                print("Preparing DOM: Injecting global width fixes and extracting AI text...")
                clean_dom = page.evaluate("""() => {
                    // 1. Hide common annoying widgets completely (Live chat, Cookie popups, floating WhatsApp buttons)
                    const annoyances = document.querySelectorAll('.cookie-banner, #cookie-notice, iframe[src*="chat"], .whatsapp-button, .e-contact-buttons__chat-button');
                    annoyances.forEach(el => el.remove());

                    // 2. Find all elements on the page
                    const allElements = document.querySelectorAll('*');
                    
                    // 3. Loop through and change 'fixed' or 'sticky' to 'relative'
                    for (let el of allElements) {
                        const style = window.getComputedStyle(el);
                        if (style.position === 'fixed' || style.position === 'sticky') {
                            el.style.setProperty('position', 'relative', 'important');
                        }
                    }

                    // Extract text for Gemini
                    let interactiveElements = Array.from(document.querySelectorAll('a, button')).map(el => {
                        let text = (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\\n/g, ' ').substring(0, 40);
                        let href = el.getAttribute('href') || 'No Href';
                        return `[${el.tagName}] Text: "${text}" | Href: ${href}`;
                    }).join('\\n');
                    
                    let visibleText = document.body.innerText.replace(/\\s+/g, ' ').substring(0, 15000);

                    return `--- INTERACTIVE ELEMENTS (LINKS/BUTTONS) ---\\n${interactiveElements}\\n\\n--- VISIBLE PAGE TEXT ---\\n${visibleText}`;
                }""")

                # ==========================================
                # PHASE 5: THE PERFECT SCREENSHOT
                # ==========================================
                os.makedirs(SCREENSHOT_DIR, exist_ok=True)
                safe_filename = url.replace("https://", "").replace("http://", "")
                for char in ['/', '\\', '?', '%', '*', ':', '|', '"', '<', '>', '=', '&']:
                    safe_filename = safe_filename.replace(char, '_')
                safe_filename = safe_filename[:150] + ".png"
                save_path = os.path.join(SCREENSHOT_DIR, safe_filename)

                body_locator = page.locator("body")

                if SAVE_LOCAL_SCREENSHOTS:
                    # Taking a screenshot of an element automatically captures its full height and width
                    screenshot_bytes = body_locator.screenshot(path=save_path)
                    print(f"📸 Saved targeted body screenshot to: {save_path}")
                else:
                    screenshot_bytes = body_locator.screenshot()
                    print("⚡ Processing targeted body screenshot in memory only")

                screenshot_image = PIL.Image.open(io.BytesIO(screenshot_bytes))

                prompt = f"""
                System Role:
                You are Top 10 Senior UX QA Auditor performing professional website Quality Control (QC) in the world.
                You analyze using:
                1. Full-page Screenshot
                2. Cleaned Text Snippet (links + visible text)

                --------------------------------
                STRICT RULES (VERY IMPORTANT)
                --------------------------------
                1. DO NOT act as a code reviewer.
                - Ignore HTML structure, divs, classes, missing tags.

                2. DO NOT flag ALL '#' or 'javascript:void(0)' as broken automatically.
                - DO NOT flag if likely:
                    - Navigation
                    - Modal trigger
                    - Dropdown toggle
                    - Button action (Submit, Close, Accept, etc.)

                3. AVOID DUPLICATION:
                - If the SAME issue appears multiple times (e.g. cookie buttons),
                    GROUP into ONE issue.
                - Do NOT repeat identical findings across the same page.

                4. PRIORITIZE REAL UX IMPACT:
                Focus on:
                - Broken flows
                - Misleading UI
                - Layout issues
                - Missing/incorrect data
                - Non-functional features

                5. LAYOUT DETECTION RULES (VISUAL PRIORITY)
                When analyzing the screenshot, apply these concrete checks:

                i. OVERLAP DETECTION
                - Identify elements visually covering others:
                - Text on top of image
                - Buttons covering content
                - Navigation arrows overlapping cards
                - Keywords: "overlapping", "covering", "blocking"

                ii. SPACING ISSUES
                - Look for:
                - Large empty gaps between sections
                - Uneven spacing between repeated items (cards, lists)
                - Content too close to edges
                - Keywords: "excess spacing", "inconsistent spacing", "misaligned"

                iii. ALIGNMENT
                - Check if elements are aligned consistently:
                - Buttons not aligned with inputs
                - Cards not in grid
                - Keywords: "misaligned", "not aligned with"

                iv. SIZE CONSISTENCY
                - Compare repeated elements:
                - Cards
                - Icons
                - Images
                - Keywords: "inconsistent size", "not uniform"

                v. VISIBILITY
                - Check if elements are hard to see:
                - Low contrast text
                - Hidden icons
                - Keywords: "low visibility", "hard to read"

                IMPORTANT:
                - ONLY report layout issues that are clearly visible
                - DO NOT guess hidden CSS problems

                --------------------------------
                QC CATEGORIES (USE THESE EXACT NAMES)
                --------------------------------
                1. Link & Navigation
                2. Layout & Spacing
                3. UI & Styling Consistency
                4. Functional & Logic
                5. Content & Data Accuracy
                6. Media & Assets
                7. Forms & Inputs
                8. UX & Interaction
                9. System Logic & Data
                10. Security & Permissions
                11. Copywriting & Branding

                --------------------------------
                SEVERITY LEVELS (MANDATORY)
                --------------------------------
                - Critical → breaks core functionality or blocks user flow
                - Need Action → impacts usability but not blocking
                - Minor → cosmetic / low impact

                --------------------------------
                HOW TO IDENTIFY ISSUES (SMART RULES)
                --------------------------------

                ✔ Link Issues:
                - Broken navigation (Page not found, wrong URL)
                - Misleading links (label ≠ destination), alert user to check instead of flagging it as error

                ✘ DO NOT FLAG:
                - Buttons like "Submit", "Close", "Accept Cookies" unless clearly non-functional visually

                ✔ Functional Issues:
                - Filters not working
                - Search not working
                - Buttons that SHOULD trigger action but clearly don’t

                ✔ Layout Issues:
                - Overlapping elements
                - Misalignment
                - Excess whitespace
                - Content overflow

                ✔ Content Issues:
                - Dummy text (Lorem Ipsum)
                - Missing info (year, labels)
                - Truncated text

                ✔ UX Issues:
                - No feedback after action
                - No active states
                - Confusing modals
                - Blocking overlays

                ✔ Forms:
                - Missing validation
                - Poor labeling
                - Missing key features (show/hide password)

                ✔ Data Logic:
                - Inconsistent dates
                - Duplicate UI elements
                - Wrong default values

                --------------------------------
                OUTPUT RULES (STRICT)
                --------------------------------

                Return ONLY a JSON array.

                Each issue must follow:

                [
                {{
                    "Page Name": "{page_name}",
                    "URL": "{url}",
                    "Severity": "Critical | Need Action | Minor",
                    "Issues": "[QC Category]: [Short, clear UX issue]",
                    "Suggestions": "[Direct fix, actionable]"
                }}
                ]

                --------------------------------
                WRITING STYLE (VERY IMPORTANT)
                --------------------------------
                - Short and direct (like real QA report)
                - No long explanations
                - No technical jargon
                - Focus on WHAT is wrong, not WHY internally

                GOOD EXAMPLE:
                "Search function is not working"

                BAD EXAMPLE:
                "The search input appears to lack functional backend integration..."

                --------------------------------
                GROUPING RULES (IMPORTANT)
                --------------------------------
                Instead of:
                ❌ 10 issues for each broken button

                Do:
                ✅ "Multiple buttons in modal are not functioning"

                --------------------------------
                GOAL
                --------------------------------
                Produce clean, professional QC findings similar to real QA reports:
                - Concise
                - Non-repetitive
                - Actionable
                - UX-focused

                --------------------------------
                INPUT DATA
                --------------------------------
                Page Name: {page_name}
                URL: {url}
                Cleaned Text Data:
                {clean_dom}
                """
                
                print("Analyzing via Gemini...")
                ai_response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[screenshot_image, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", 
                        temperature=0.1 
                    )
                )

                res_text = ai_response.text
                print(f"Raw AI Output: {res_text}")

                try:
                    clean_json = res_text.replace("```json", "").replace("```", "").strip()
                    
                    start_idx = clean_json.find('[')
                    end_idx = clean_json.rfind(']')
                    
                    if start_idx != -1 and end_idx != -1:
                        clean_json = clean_json[start_idx:end_idx + 1]
                        
                    issues_list = json.loads(clean_json)
                    
                    if not issues_list:
                        update_sheet([page_name, url, "🟢 Pass - No visual issues detected", "-", time.ctime()])
                        print(f"Result: 0 issues found.")
                    else: 
                        for issue in issues_list:
                            row_data = [
                                issue.get("Page Name", page_name),
                                issue.get("URL", url),
                                issue.get("Issues", "Unknown Issue"),
                                issue.get("Suggestions", "No suggestion provided"),
                                time.ctime()
                            ]
                            update_sheet(row_data)
                        print(f"Result: Uploaded {len(issues_list)} issues to Google Sheets.")

                except json.JSONDecodeError as json_err:
                    print(f"Failed to parse JSON: {json_err}")
                    update_sheet([page_name, url, "🔴 Error", f"JSON Parse Failed: {res_text}", time.ctime()])

            except Exception as e:
                error_msg = str(e)
                # Check if the error is a 429 API Limit / Quota error
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                    print("\n")
                    print("🚨 CRITICAL: Gemini API Limit Reached! Stopping audit.")
                    break
                
                # For all other random errors (like a timeout or bad URL), log normally
                print(f"Error on {url}: {e}")
                update_sheet([page_name if 'page_name' in locals() else "Unknown", url, "🔴 System Error", str(e), time.ctime()])
            
            print(f"Cooling down for {COOLDOWN_SECONDS} seconds to respect API limits...")
            time.sleep(COOLDOWN_SECONDS)
        
        browser.close()

if __name__ == "__main__":
    run_audit()