"""
Call Analyzer for GitHub Actions
================================
1. Analyzes new "Not Interested" calls
2. Updates the HTML dashboard with fresh data
"""

import os
import json
import requests
import tempfile
import re
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from groq import Groq

# Get secrets from environment (GitHub Actions)
GOOGLE_CREDENTIALS = os.environ.get('GOOGLE_CREDENTIALS', '')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
DEEPGRAM_API_KEY = os.environ.get('DEEPGRAM_API_KEY', '')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID', '1Y8nHFCR5hqEwqjurcYjMob3IyAHoO4pp9uDcazwSIuQ')

RECORDING_USERNAME = "adversus_recording"
RECORDING_PASSWORD = "c1byqg63fpwsg48co4soc0k"

COL_CAMPAIGN = 0
COL_TIMESTAMP = 1
COL_LEAD_STATUS = 5
COL_AGENT = 7
COL_DURATION = 8
COL_RECORDING = 9
COL_FIRST_NAME = 11
COL_LAST_NAME = 12
COL_DOG_NAME = 15

RESULTS_SHEET = "Call Analysis"

ANALYSIS_PROMPT = """You are an expert Sales Coach for Butternut Box, a premium dog food brand. 

Analyze this call transcript and score it against these criteria. The call resulted in "Not Interested" - identify what went wrong and what could be improved.

## SCORING CRITERIA (Score each 1-10):

### 1. INTRODUCTION (Max 10)
- Did agent state their name and "Butternut Box" within first 10 seconds?
- Did they use the pet's name in the opener?
- Did they avoid "Sorry to bother you" or "Is now a good time?"
- Did they frame the call positively (reward/gift language)?

### 2. DISCOVERY (Max 10)
- Did they ask what the customer already knows about Butternut?
- Did they probe for WHY they're interested/what problems exist?
- Did they identify a specific "nugget" (fussy, health issue, etc.)?
- Did they ask follow-up questions when customer mentioned current food?

### 3. SOLUTION MATCHING (Max 10)
- Did they connect Butternut features to the customer's specific needs?
- Did they use the pet's name during the pitch?
- Did they paint visual pictures (size comparisons, storage, etc.)?

### 4. PRICE PRESENTATION (Max 10)
- Did they build value BEFORE mentioning price?
- Did they explain both taster price AND ongoing subscription cost?
- Did they anchor to daily cost or compare to current spend?
- Did they allow silence after price reveal?

### 5. OBJECTION HANDLING (Max 10)
- When customer said no/hesitated, did agent probe for the real reason?
- Did they attempt at least one polite challenge/pushback?
- Did they reframe concerns positively?

### 6. ENERGY & RAPPORT (Max 10)
- Did agent maintain positive energy throughout?
- Did they use the pet's name regularly (3+ times)?
- Was there any rapport/humor/warmth?
- Did they avoid monotone delivery?

## RED FLAGS TO IDENTIFY:
- Speaking over customer
- Monologues >45 seconds without check-in
- Price mentioned too early (within first 2 mins)
- Giving up immediately after first objection
- Generic pitch without personalization

## OUTPUT FORMAT (JSON):
{
    "overall_score": <total out of 60>,
    "scores": {
        "introduction": <1-10>,
        "discovery": <1-10>,
        "solution_matching": <1-10>,
        "price_presentation": <1-10>,
        "objection_handling": <1-10>,
        "energy_rapport": <1-10>
    },
    "red_flags": ["list of red flags identified"],
    "what_went_wrong": "1-2 sentence summary of why they lost the sale",
    "top_improvement": "The single most important thing this agent should work on",
    "key_moments": "Brief summary of key moments in the call"
}

## TRANSCRIPT TO ANALYZE:

Agent: {agent_name}
Pet Name: {dog_name}
Customer: {customer_name}
Call Duration: {duration}

---
{transcript}
---

Provide your analysis in the JSON format specified above. Be specific and actionable in your feedback.
"""


def get_credentials():
    """Load Google credentials from environment"""
    if GOOGLE_CREDENTIALS:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    raise ValueError("GOOGLE_CREDENTIALS not set")


def get_sheets_service(credentials):
    return build('sheets', 'v4', credentials=credentials)


def get_sheet_data(service, range_name):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=range_name
    ).execute()
    return result.get('values', [])


def filter_not_interested(data):
    if not data or len(data) < 2:
        return []
    rows = data[1:]
    filtered = []
    for i, row in enumerate(rows):
        if len(row) > COL_RECORDING:
            lead_status = row[COL_LEAD_STATUS] if len(row) > COL_LEAD_STATUS else ""
            recording_url = row[COL_RECORDING] if len(row) > COL_RECORDING else ""
            if lead_status.lower() == "not interested" and recording_url:
                filtered.append({
                    'row_index': i + 2,
                    'campaign': row[COL_CAMPAIGN] if len(row) > COL_CAMPAIGN else "",
                    'timestamp': row[COL_TIMESTAMP] if len(row) > COL_TIMESTAMP else "",
                    'agent': row[COL_AGENT] if len(row) > COL_AGENT else "",
                    'duration': row[COL_DURATION] if len(row) > COL_DURATION else "",
                    'recording_url': recording_url,
                    'first_name': row[COL_FIRST_NAME] if len(row) > COL_FIRST_NAME else "",
                    'last_name': row[COL_LAST_NAME] if len(row) > COL_LAST_NAME else "",
                    'dog_name': row[COL_DOG_NAME] if len(row) > COL_DOG_NAME else ""
                })
    return filtered


def get_analyzed_recordings(service):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=f"'{RESULTS_SHEET}'!B:B"
        ).execute()
        values = result.get('values', [])
        return set(row[0] for row in values[1:] if row)
    except:
        return set()


def create_results_sheet(service):
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = [s['properties']['title'] for s in spreadsheet['sheets']]
        if RESULTS_SHEET not in sheets:
            service.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={'requests': [{'addSheet': {'properties': {'title': RESULTS_SHEET}}}]}
            ).execute()
            header = ["Analyzed Date", "Recording URL", "Agent", "Customer", "Dog Name",
                      "Call Duration", "Overall Score", "Introduction", "Discovery",
                      "Solution Matching", "Price Presentation", "Objection Handling",
                      "Energy & Rapport", "Red Flags", "What Went Wrong", "Top Improvement",
                      "Key Moments", "Full Transcript", "Call Date"]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"'{RESULTS_SHEET}'!A1",
                valueInputOption='RAW',
                body={'values': [header]}
            ).execute()
    except Exception as e:
        print(f"Sheet error: {e}")


def write_result(service, result):
    row = [
        result.get('analyzed_date', ''), result.get('recording_url', ''),
        result.get('agent', ''), result.get('customer', ''), result.get('dog_name', ''),
        result.get('duration', ''), result.get('overall_score', ''),
        result.get('introduction', ''), result.get('discovery', ''),
        result.get('solution_matching', ''), result.get('price_presentation', ''),
        result.get('objection_handling', ''), result.get('energy_rapport', ''),
        result.get('red_flags', ''), result.get('what_went_wrong', ''),
        result.get('top_improvement', ''), result.get('key_moments', ''),
        result.get('transcript', ''), result.get('call_date', '')
    ]
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{RESULTS_SHEET}'!A:S",
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body={'values': [row]}
    ).execute()


def download_recording(url):
    try:
        response = requests.get(url, auth=(RECORDING_USERNAME, RECORDING_PASSWORD), timeout=120)
        if response.status_code == 200 and len(response.content) > 1000:
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                f.write(response.content)
                return f.name
    except Exception as e:
        print(f"Download error: {e}")
    return None


def transcribe_audio(audio_path):
    try:
        with open(audio_path, 'rb') as f:
            buffer_data = f.read()
        response = requests.post(
            "https://api.deepgram.com/v1/listen",
            params={"model": "nova-2", "language": "en-GB", "smart_format": "true", "punctuate": "true"},
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": "audio/mp3"},
            data=buffer_data, timeout=300
        )
        if response.status_code == 200:
            result = response.json()
            return result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")
    except Exception as e:
        print(f"Transcribe error: {e}")
    return None


def analyze_transcript(transcript, call_info):
    if len(transcript) < 50:
        return {
            "overall_score": 0,
            "scores": {"introduction": 0, "discovery": 0, "solution_matching": 0,
                       "price_presentation": 0, "objection_handling": 0, "energy_rapport": 0},
            "red_flags": ["Call too short"],
            "what_went_wrong": "Call too brief",
            "top_improvement": "N/A",
            "key_moments": ""
        }
    try:
        client = Groq(api_key=GROQ_API_KEY)
        prompt = ANALYSIS_PROMPT.replace('{agent_name}', call_info.get('agent', 'Unknown'))
        prompt = prompt.replace('{dog_name}', call_info.get('dog_name', 'Unknown'))
        prompt = prompt.replace('{customer_name}', f"{call_info.get('first_name', '')} {call_info.get('last_name', '')}".strip() or 'Unknown')
        prompt = prompt.replace('{duration}', call_info.get('duration', 'Unknown'))
        prompt = prompt.replace('{transcript}', transcript)
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an expert sales coach. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3, max_tokens=2000
        )
        response_text = response.choices[0].message.content
        json_str = response_text
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1]
        start_idx, end_idx = json_str.find('{'), json_str.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_str = json_str[start_idx:end_idx+1]
        return json.loads(json_str.strip())
    except Exception as e:
        print(f"Analysis error: {e}")
    return None


def get_call_date_from_sheet1(service, recording_url):
    """Get the call date from Sheet1 based on recording URL"""
    try:
        data = get_sheet_data(service, 'Sheet1!A:U')
        for row in data[1:]:
            if len(row) > COL_RECORDING and row[COL_RECORDING] == recording_url:
                if len(row) > COL_TIMESTAMP and row[COL_TIMESTAMP]:
                    timestamp = row[COL_TIMESTAMP]
                    if 'T' in timestamp:
                        return timestamp.split('T')[0]
                    return timestamp[:10] if len(timestamp) >= 10 else timestamp
        return ""
    except:
        return ""


def analyze_new_calls(service):
    """Analyze any new Not Interested calls"""
    create_results_sheet(service)
    analyzed = get_analyzed_recordings(service)
    data = get_sheet_data(service, 'Sheet1!A:U')
    not_interested = filter_not_interested(data)
    to_analyze = [r for r in not_interested if r['recording_url'] not in analyzed]
    
    print(f"Found {len(to_analyze)} new calls to analyze")
    
    for i, call in enumerate(to_analyze[:5], 1):
        print(f"\nProcessing call {i}: {call['agent']} -> {call['first_name']}")
        
        audio_path = download_recording(call['recording_url'])
        if not audio_path:
            continue
        
        try:
            transcript = transcribe_audio(audio_path)
            if not transcript:
                continue
            
            analysis = analyze_transcript(transcript, call)
            if not analysis:
                continue
            
            call_date = call['timestamp'].split('T')[0] if 'T' in call['timestamp'] else call['timestamp'][:10] if call['timestamp'] else ""
            
            key_moments = analysis.get('key_moments', '')
            if isinstance(key_moments, list):
                key_moments = '; '.join([f"{km.get('timestamp', '')} {km.get('issue', '')}" for km in key_moments if isinstance(km, dict)])
            
            result = {
                'analyzed_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'recording_url': call['recording_url'],
                'agent': call['agent'],
                'customer': f"{call['first_name']} {call['last_name']}".strip(),
                'dog_name': call['dog_name'],
                'duration': call['duration'],
                'overall_score': analysis.get('overall_score', ''),
                'introduction': analysis.get('scores', {}).get('introduction', ''),
                'discovery': analysis.get('scores', {}).get('discovery', ''),
                'solution_matching': analysis.get('scores', {}).get('solution_matching', ''),
                'price_presentation': analysis.get('scores', {}).get('price_presentation', ''),
                'objection_handling': analysis.get('scores', {}).get('objection_handling', ''),
                'energy_rapport': analysis.get('scores', {}).get('energy_rapport', ''),
                'red_flags': ', '.join(analysis.get('red_flags', [])) if isinstance(analysis.get('red_flags'), list) else analysis.get('red_flags', ''),
                'what_went_wrong': analysis.get('what_went_wrong', ''),
                'top_improvement': analysis.get('top_improvement', ''),
                'key_moments': key_moments,
                'transcript': transcript[:5000],
                'call_date': call_date
            }
            write_result(service, result)
            print(f"   Score: {analysis.get('overall_score', 'N/A')}/60")
        finally:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
    
    return len(to_analyze) > 0


def get_all_analysis_data(service):
    """Get all analysis data and Sheet1 data for the dashboard"""
    analysis_data = get_sheet_data(service, f"'{RESULTS_SHEET}'!A:S")
    sheet1_data = get_sheet_data(service, 'Sheet1!A:U')
    
    if not analysis_data or len(analysis_data) < 2:
        return []
    
    header = analysis_data[0]
    rows = analysis_data[1:]
    
    recording_to_region = {}
    for row in sheet1_data[1:]:
        if len(row) > COL_RECORDING:
            recording_url = row[COL_RECORDING]
            campaign = row[COL_CAMPAIGN] if len(row) > COL_CAMPAIGN else ""
            region = "UK" if "UK" in campaign.upper() else "Ireland"
            recording_to_region[recording_url] = region
    
    calls = []
    for row in rows:
        if len(row) < 7:
            continue
        
        overall = row[6] if len(row) > 6 else ""
        if overall == "SKIPPED" or not overall:
            continue
        
        try:
            overall_score = int(overall)
        except:
            continue
        
        recording_url = row[1] if len(row) > 1 else ""
        region = recording_to_region.get(recording_url, "Ireland")
        
        duration_str = row[5] if len(row) > 5 else "0"
        try:
            duration = int(duration_str)
        except:
            duration = 0
        
        call_date = row[18] if len(row) > 18 else ""
        if not call_date:
            call_date = datetime.now().strftime('%Y-%m-%d')
        
        # Build authenticated recording URL
        auth_recording_url = ""
        if recording_url:
            # Embed credentials in URL for audio playback
            auth_recording_url = recording_url.replace("https://", "https://adversus_recording:c1byqg63fpwsg48co4soc0k@")
        
        calls.append({
            "date": call_date,
            "agent": row[2] if len(row) > 2 else "",
            "customer": row[3] if len(row) > 3 else "",
            "dog_name": row[4] if len(row) > 4 else "",
            "duration": duration,
            "overall_score": overall_score,
            "introduction": int(row[7]) if len(row) > 7 and row[7] else 0,
            "discovery": int(row[8]) if len(row) > 8 and row[8] else 0,
            "solution_matching": int(row[9]) if len(row) > 9 and row[9] else 0,
            "price_presentation": int(row[10]) if len(row) > 10 and row[10] else 0,
            "objection_handling": int(row[11]) if len(row) > 11 and row[11] else 0,
            "energy_rapport": int(row[12]) if len(row) > 12 and row[12] else 0,
            "red_flags": row[13] if len(row) > 13 else "",
            "what_went_wrong": row[14] if len(row) > 14 else "",
            "top_improvement": row[15] if len(row) > 15 else "",
            "key_moments": row[16] if len(row) > 16 else "",
            "region": region,
            "recording_url": auth_recording_url
        })
    
    return calls


def update_html_dashboard(calls):
    """Update the index.html with new data"""
    html_path = "index.html"
    
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()
    
    js_data = json.dumps(calls, indent=2)
    
    # Find and replace the sampleData - use string find/replace instead of regex
    # to avoid issues with backslashes in URLs
    start_marker = 'const sampleData = ['
    end_marker = '];'
    
    start_idx = html.find(start_marker)
    if start_idx == -1:
        print("Could not find sampleData in HTML")
        return
    
    # Find the matching end bracket
    bracket_count = 0
    end_idx = start_idx + len(start_marker) - 1
    for i in range(start_idx + len(start_marker) - 1, len(html)):
        if html[i] == '[':
            bracket_count += 1
        elif html[i] == ']':
            bracket_count -= 1
            if bracket_count == 0:
                end_idx = i + 2  # Include '];'
                break
    
    new_html = html[:start_idx] + f'const sampleData = {js_data};' + html[end_idx:]
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_html)
    
    print(f"Updated HTML with {len(calls)} calls")


def main():
    print("=" * 50)
    print(f"Call Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)
    
    credentials = get_credentials()
    service = get_sheets_service(credentials)
    
    new_calls_analyzed = analyze_new_calls(service)
    
    # Always update dashboard with latest data (including recording URLs)
    print("\nUpdating dashboard with all call data...")
    calls = get_all_analysis_data(service)
    if calls:
        update_html_dashboard(calls)
        print("Dashboard updated!")
    else:
        print("No call data found.")
    
    print("\nDone!")


if __name__ == "__main__":
    main()
