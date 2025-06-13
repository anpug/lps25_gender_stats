# %%
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import pandas as pd
import gender_guesser.detector as gender
import time
import re


# === Function to fetch text content from session page ===
def get_visible_text_from_page(url):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run in headless mode
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get(url)
    time.sleep(5)  # Allow JS to load
    text = driver.find_element("tag name", "body").text
    driver.quit()
    return text

# === Function to extract title, chairs, presenters from raw text ===
def extract_info_from_text(text):
    lines = text.splitlines()
    title = lines[13] if len(lines) >= 14 else "N/A"

    # Extract chairs
    chairs = []
    chair_match = re.search(r"Chair\(s\)\s*(.*?)\s*(Room|Date|Time)", text, re.DOTALL)
    if chair_match:
        chair_line = chair_match.group(1).strip()
        chairs = [name.strip() for name in re.split(r",|\n", chair_line) if name.strip()]

    # Extract presenters
    presenters = re.findall(r"([\w\.\-\' ]+?)\s*\(Presenter\)", text)
    presenters = [p.strip() for p in presenters]

    # Extract speakers
    speakers = []
    speaker_match = re.search(r"Speakers:\s*\n(.*?)(?:\n\n|\Z)", text, re.DOTALL)
    if speaker_match:
        block = speaker_match.group(1).strip()
        raw_speakers = [line.strip() for line in block.split("\n") if line.strip()]
        speakers = [s for s in raw_speakers if not s.startswith("©")]

    # Extract moderators
    moderators = []
    moderators_match = re.search(r"Moderators:\s*\n(.*?)(?:\n\n|\Z)", text, re.DOTALL)
    if moderators_match:
        block = moderators_match.group(1).strip()
        raw_mods = [line.strip() for line in block.split("\n") if line.strip()]
        moderators = [m for m in raw_mods if not m.startswith("©")]

    # Extract panel members
    panelists = []
    panel_match = re.search(r"Panel members:\s*\n(.*?)(?:\n\n|\Z)", text, re.DOTALL)
    if panel_match:
        block = panel_match.group(1).strip()
        raw_panel = [line.strip() for line in block.split("\n") if line.strip()]
        panelists = [p for p in raw_panel if not p.startswith("©")]

    return title, chairs, presenters, speakers, moderators, panelists

def remove_digits(text):
    return re.sub(r'\d+', '', text).strip()

def remove_titles(name):
    if not isinstance(name, str):
        return name
    return re.sub(r'\b(dr|prof|mr|ms|mrs|miss|pr)\.?\s+', '', name, flags=re.IGNORECASE).strip()

def detect_gender(full_name):
    if not full_name or full_name.strip().lower() == "n/a":
        return "unknown"
    first_name = re.findall(r'\b[A-Z][a-z]+\b', full_name)
    if not first_name:
        return "unknown"
    return d.get_gender(first_name[0])

def process_session_dataframe(df):
    # Extract 7-character prefixes
    df["title_prefix"] = df["title"].str[:7]
    
    # Split chairs and presenters into lists
    df["chair_list"] = df["chairs"].str.split(",")
    df["presenter_list"] = df["presenters"].str.split(",")

    # Ensure two columns for chairs (fill missing with "N/A")
    df["chair1"] = df["chair_list"].apply(lambda x: x[0].strip() if len(x) > 0 else "N/A")
    df["chair2"] = df["chair_list"].apply(lambda x: x[1].strip() if len(x) > 1 else "N/A")

    # Explode presenters into individual rows
    df_long = df.explode("presenter_list").reset_index(drop=True)

    # Create final DataFrame
    final_df = df_long[["presenter_list", "chair1", "chair2", "title"]].rename(
        columns={"presenter_list": "presenter"}
    )

    # Clean up names
    for col in ["presenter", "chair1", "chair2"]:
        final_df[col] = final_df[col].apply(remove_digits).apply(remove_titles)

    # Remove empty presenters
    final_df = final_df[final_df["presenter"].str.strip() != ""].reset_index(drop=True)

    # Gender detection
    final_df["presenter_gender"] = final_df["presenter"].apply(detect_gender)
    final_df["chair1_gender"] = final_df["chair1"].apply(detect_gender)
    final_df["chair2_gender"] = final_df["chair2"].apply(detect_gender)

    return final_df


# === List of session IDs ===
with open("session_ids.txt", "r") as f:
    session_ids = [line.strip() for line in f if line.strip()]

# === Base URL for ESA LPS25 session pages ===
base_url = "https://lps25.esa.int/programme/programme-session/?id="

# === Store all session data ===
data_rows = []

for sid in session_ids:
    url = base_url + sid
    try:
        print(f"Processing session: {sid}")
        text = get_visible_text_from_page(url)
        title, chairs, presenters, speakers, moderators, panelists = extract_info_from_text(text)
        data_rows.append({
            "session_id": sid,
            "title": title,
            "chairs": ", ".join(chairs),
            "presenters": ", ".join(presenters),
            "speakers": ", ".join(speakers),
            "moderators": ", ".join(moderators),
            "panelists": ", ".join(panelists)
        })
    except Exception as e:
        print(f"Error processing {sid}: {e}")
        data_rows.append({
            "session_id": sid,
            "title": "ERROR",
            "chairs": "",
            "presenters": "",
            "speakers": "",
            "moderators": "",
            "panelists": ""
        })

# === Create and save the DataFrame ===
df = pd.DataFrame(data_rows)
df.to_csv("esa_lps25_sessions.csv", index=False)
print("Saved session data to esa_lps25_sessions.csv")


oral_df = df[
    (df["chairs"].str.strip().str.lower() != "n/a") &
    (df["chairs"].str.strip() != "") &
    (df["presenters"].str.strip() != "")
].reset_index(drop=True)

poster_df = df[
    (df["chairs"].str.strip().str.lower() == "n/a") &
    (df["presenters"].str.strip() != "")
].reset_index(drop=True)

panel_df = df[
    (df["speakers"].str.strip() != "") |
    (df["moderators"].str.strip() != "") |
    (df["panelists"].str.strip() != "")
].reset_index(drop=True)


d = gender.Detector()

# Apply processing to oral and poster DataFrames
final_oral_df = process_session_dataframe(oral_df)
final_poster_df = process_session_dataframe(poster_df)


# Initialize storage
panel_rows = []

# Loop over panel_df
for _, row in panel_df.iterrows():
    title = row["title"]
    
    for role in ["speakers", "moderators", "panelists"]:
        names_raw = row.get(role, "")
        if isinstance(names_raw, str):
            names = [n.strip() for n in names_raw.split(",") if n.strip()]
            for name in names:
                clean_name = remove_titles(remove_digits(name))
                if clean_name:
                    panel_rows.append({
                        "name": clean_name,
                        "role": role[:-1],  # convert 'speakers' -> 'speaker'
                        "title": title,
                        "gender": detect_gender(clean_name)
                    })

# Create the final DataFrame
final_panel_df = pd.DataFrame(panel_rows)

# Save the final DataFrames
final_oral_df.to_csv("esa_lps25_oral_sessions.csv", index=False)
final_poster_df.to_csv("esa_lps25_poster_sessions.csv", index=False)
final_panel_df.to_csv("esa_lps25_panel_sessions.csv", index=False)
print("Saved final DataFrames to esa_lps25_oral_sessions.csv, esa_lps25_poster_sessions.csv, esa_lps25_panel_sessions.csv")
# %%
