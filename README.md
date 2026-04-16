# 🔍Auto QC: AI-Powered Website Auditor

## 📖Overview
Auto QC is an automated quality control script designed to crawl website sitemaps and audit pages using Playwright and the Gemini Vision API. It captures full-page visual context and logs actionable findings directly to a designated Google Sheet. 

**Note:** While the script captures the full UI, it is particularly optimized and highly effective for identifying **grammar, copywriting, and typography errors** across web pages, rather than serving as a comprehensive UI/UX layout auditor.

## ⚙️Prerequisites
Before running this tool, ensure you have the following items:
* Python 3.8+ installed
* Google Cloud Console account (Google Sheets API Service Account - "https://console.cloud.google.com/")
* Gemini API Key (Google AI Studio - "https://aistudio.google.com/")

## 🚀Setup & Installation

1. **Clone the repository and navigate to the directory:**
   ```bash
   git clone https://github.com/Zyuan04/website-qc-ai.git
   cd website-qc-ai.git
   ```

2. **Install dependencies:**
    ```bash
    playwright install chromium
    ```
    
    * Configure Authentication:
    Obtain a credentials.json file from your Google Cloud Service Account and place it in the root directory.
   
    * Copy the .env.example file, rename it to .env, and add your API keys:
    Code snippet
    ```bash
    GEMINI_API_KEY="your_gemini_api_key_here"
    SPREADSHEET_ID="your_google_sheet_id_here"
    ```
    
## 🛠️Configuration
Before running an audit, open main.py and adjust the variables in the --- 1. CONFIGURATION --- block to match your current project:

* **USE_URL:** Set to True to scan a live sitemap, or False to use a local XML file.

* **SITEMAP_URL / SITEMAP_FILE:** The target sitemap location.
* To get SITEMAP_FILE: Use plugin to export sitemap file (.xml) or use online sitemap generator "www.xml-sitemaps.com".

* **GOOGLE_SHEET_TAB_NAME:** The exact name of the tab in your target Google Sheet.

* **SAVE_LOCAL_SCREENSHOTS:** Set to False if you want a "No-Trace" run to save local storage space.

* **GEMINI_MODEL:** Free Tier and Support Vision Models - gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3.1-flash-lite-preview.
* Check "https://ai.google.dev/gemini-api/docs/models" for updated models.

## 💻Usage
Run the script via the terminal:
```bash
python main.py
```

The script will initialize a Chromium browser, bypass standard Cloudflare checks, force-load lazy assets (like Elementor/JetEngine), and process screenshots through Gemini. Results are appended automatically to your configured Google Sheet.
