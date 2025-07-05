import requests
from bs4 import BeautifulSoup
import re
import time
import pandas as pd
import numpy as np
import json
import shutil


BASE_URL = "https://unityleague.gg"
LEADERBOARD_URL = f"{BASE_URL}/ranking/eu2025/BE/?showAll=true"

def get_soup_from_url(url):
    response = requests.get(url)
    response.raise_for_status()  # Raise exception for bad status codes
    return BeautifulSoup(response.text, 'html.parser')

def extract_players(soup):
    players = []
    for row in soup.select("table#rankingTable tbody tr"):
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
            
        player_tag = cols[2].find("a")
        if player_tag:
            players.append({
                "rank": cols[0].get_text(strip=True),
                "points": int(cols[1].get_text(strip=True)),
                "name": player_tag.get_text(strip=True),
                "profile_url": BASE_URL + player_tag['href'],
                "player_id": player_tag['href'].split('/')[2]
            })
    return players

def parse_player_profile(url):
    try:
        soup = get_soup_from_url(url)
        events_section = soup.find("h2", string=re.compile("Event history", re.I))
        if not events_section:
            return None

        total_wins, total_losses, total_draws = 0, 0, 0
        draft_weekly_count = 0
        
        for row in events_section.find_next("table").select("tbody tr"):
            cols = row.find_all('td')
            if len(cols) < 7:
                continue

            # Check format and event type
            if cols[6].text.strip() == "Limited" and ("draft" in cols[1].text.lower() and "weekly" in cols[1].text.lower()) or 'prerelease' in cols[1].text.lower():
                match = re.match(r"(\d+)\s*-\s*(\d+)\s*-\s*(\d+)", cols[3].text.strip())
                if match:
                    total_wins += int(match.group(1))
                    total_losses += int(match.group(2))
                    total_draws += int(match.group(3))
                    draft_weekly_count += 1

        if draft_weekly_count == 0:
            return None

        total_matches = total_wins + total_losses + total_draws
        return {
            "wins": total_wins,
            "losses": total_losses,
            "draws": total_draws,
            "winrate": round((total_wins + 0.5 * total_draws) / total_matches * 100, 1),
            "limited_events": draft_weekly_count,
            "matches": total_matches
        }
        
    except Exception as e:
        print(f"Error processing profile: {e}")
        return None

def main():
    players = extract_players(get_soup_from_url(LEADERBOARD_URL))
    results = []
    
    for player in players:
        try:
            if stats := parse_player_profile(player['profile_url']):
                player.update(stats)
                results.append(player)
                print(f"Processed {player['name']}")
            time.sleep(1)
        except Exception as e:
            print(f"Error with {player['name']}: {e}")
    
    # Create DataFrame and save results
    df = pd.DataFrame(results)
    
    # Timestamp for update
    df['update_time'] = pd.Timestamp.now(tz='Europe/Paris')
    df['update_time'] = df['update_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    df["matches"] = df["matches"].astype(float)
    df["winrate"] = df["winrate"].astype(float)
    df["perf_score"] = (df["winrate"] * np.log(df["matches"] + 1)).round(2)
    # Réinitialisation du classement
    df.sort_values('perf_score', ascending=False, inplace=True)

    df.reset_index(drop=True, inplace=True)
    df['rank'] = df.index + 1
    df['rank'] = df['rank'].astype(int)
    
    df.to_csv('draft_weekly_leaderboard.csv', index=False)
    df.to_json("leaderboard.json", orient="records", indent=2)
    return df

def update_json(df):
    
    try:
        with open('leaderboard.json', 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
        prev_df = pd.DataFrame(prev_data)
    except FileNotFoundError:
        prev_df = pd.DataFrame([])
        
    # On crée un mapping nom -> rang précédent
    if not prev_df.empty:
        prev_rank_map = prev_df.set_index('name')['rank'].to_dict()
    else:
        prev_rank_map = {}

    # Ajoute une colonne last_rank au DataFrame actuel
    df['last_rank'] = df['name'].map(prev_rank_map)


    # Sauvegarde le classement précédent
    try:
        shutil.copy('leaderboard.json', 'leaderboard_prev.json')
    except FileNotFoundError:
        # Premier lancement, pas de fichier précédent
        pass

    # Garde seulement les colonnes utiles
    cols = [
        'rank', 'name', 'wins', 'losses', 'draws', 'matches',
        'winrate', 'limited_events', 'perf_score', 'points', 'profile_url',
        'update_time', 'last_rank'
    ]
    # Si certaines colonnes n'existent pas, on les ignore
    cols = [c for c in cols if c in df.columns]

    # Sauvegarde le classement actuel
    df[cols].to_json('leaderboard.json', orient='records', force_ascii=False, indent=2)
    
    # Update last rank 
    with open('leaderboard.json') as f:
        current = json.load(f)
    with open('leaderboard_prev.json') as f:
        previous = json.load(f)

    # Build a mapping from player_id to previous rank
    prev_ranks = {p['profile_url']: p['rank'] for p in previous}

    # Add last_rank to each player in current leaderboard
    for p in current:
        p['last_rank'] = prev_ranks.get(p['profile_url'])

    # Save the enriched leaderboard
    with open('leaderboard.json', 'w') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    return df 


if __name__ == "__main__":
    df = main()
    
    df = update_json(df)
    
    print("Leaderboard updated successfully.")
