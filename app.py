import os
import requests
from flask import Flask, request, jsonify
from supabase import create_client, Client
import librosa
import soundfile as sf
from basic_pitch.inference import predict_and_save_midi
import numpy as np
import tempfile
import shutil

app = Flask(__name__)

# --- Configuration (Environment Variables) --- #
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
SOUNDSTAT_API_URL = os.environ.get("SOUNDSTAT_API_URL")
SOUNDSTAT_API_KEY = os.environ.get("SOUNDSTAT_API_KEY")

# Initialize Supabase client with service_role key for backend operations
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# Helper function to map musical keys to semitone shifts (simplified)
def get_semitone_shift(current_key, target_key):
    # This is a very simplified mapping. A real app would need a more robust music theory library.
    # For example, mapping C=0, C#=1, D=2, etc.
    key_map = {
        "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
        "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11
    }
    current_root = current_key.split(" ")[0] # e.g., "C" from "C Major"
    target_root = target_key.split(" ")[0]

    if current_root in key_map and target_root in key_map:
        return key_map[target_root] - key_map[current_root]
    return 0 # No shift if keys are not recognized

@app.route("/process-audio", methods=["POST"])
def process_audio():
    temp_dir = None
    try:
        data = request.get_json()
        audio_file_url = data.get("audio_file_url")
        user_id = data.get("user_id")
        audio_file_id = data.get("audio_file_id")
        desired_key = data.get("desired_key")
        desired_tempo = data.get("desired_tempo")
        process_midi = data.get("process_midi", True) # Default to True

        if not all([audio_file_url, user_id, audio_file_id]):
            return jsonify({"status": "error", "message": "Missing required parameters"}), 400

        temp_dir = tempfile.mkdtemp()
        original_audio_path = os.path.join(temp_dir, f"original_{audio_file_id}.wav")
        processed_audio_path = os.path.join(temp_dir, f"processed_{audio_file_id}.wav")
        midi_output_path = os.path.join(temp_dir, f"midi_{audio_file_id}.mid")

        # --- 1. Download Audio File from Supabase Storage ---
        response = requests.get(audio_file_url)
        response.raise_for_status() # Raise an exception for HTTP errors

        with open(original_audio_path, "wb") as f:
            f.write(response.content)

        y, sr = librosa.load(original_audio_path, sr=None) # Load with original sample rate

        # --- 2. Audio Analysis (Key & Tempo Detection) - if not already done by Edge Function ---
        # This is a fallback/redundancy. The Edge Function is designed to do this.
        detected_key = None
        detected_tempo = None
        if SOUNDSTAT_API_URL and SOUNDSTAT_API_KEY:
            try:
                analysis_payload = {"audio_url": audio_file_url}
                analysis_headers = {"Content-Type": "application/json", "Authorization": f"Bearer {SOUNDSTAT_API_KEY}"}
                analysis_response = requests.post(SOUNDSTAT_API_URL, json=analysis_payload, headers=analysis_headers)
                analysis_response.raise_for_status()
                analysis_result = analysis_response.json()
                detected_key = analysis_result["audio_analysis"]["key"]["value"] # Adjust based on actual API response
                detected_tempo = analysis_result["audio_analysis"]["tempo"]["value"] # Adjust based on actual API response
            except Exception as e:
                print(f"SoundStat API call failed: {e}")

        # --- 3. Audio Modification (Pitch Shifting & Time Stretching) ---
        modified_y = y
        processed_audio_url = None

        if desired_key or desired_tempo:
            # Pitch Shifting
            if desired_key and detected_key: # Only shift if a desired key and detected key are available
                semitone_shift = get_semitone_shift(detected_key, desired_key)
                if semitone_shift != 0:
                    modified_y = librosa.effects.pitch_shift(y=modified_y, sr=sr, n_steps=semitone_shift)

            # Time Stretching
            if desired_tempo and detected_tempo: # Only stretch if a desired tempo and detected tempo are available
                if detected_tempo > 0: # Avoid division by zero
                    rate = desired_tempo / detected_tempo
                    modified_y = librosa.effects.time_stretch(y=modified_y, rate=rate)

            # Save processed audio
            sf.write(processed_audio_path, modified_y, sr)

            # Upload processed audio to Supabase Storage
            with open(processed_audio_path, "rb") as f:
                processed_file_name = f"processed_{audio_file_id}.wav"
                storage_path = f"{user_id}/{processed_file_name}"
                supabase.storage.from("processed-audio").upload(storage_path, f.read(), {"contentType": "audio/wav"})
                processed_audio_url = f"{SUPABASE_URL}/storage/v1/object/public/processed-audio/{storage_path}"

        # --- 4. Audio to MIDI Conversion ---
        midi_file_url = None
        if process_midi:
            # Basic-Pitch expects a list of audio paths and an output directory
            predict_and_save_midi(audio_paths=[original_audio_path], output_dir=temp_dir)

            # Upload MIDI file to Supabase Storage
            with open(midi_output_path, "rb") as f:
                midi_file_name = f"midi_{audio_file_id}.mid"
                storage_path = f"{user_id}/{midi_file_name}"
                supabase.storage.from("midi-files").upload(storage_path, f.read(), {"contentType": "audio/midi"})
                midi_file_url = f"{SUPABASE_URL}/storage/v1/object/public/midi-files/{storage_path}"

        return jsonify({
            "status": "success",
            "message": "Audio processed successfully",
            "processed_audio_url": processed_audio_url,
            "midi_file_url": midi_file_url,
            "detected_key": detected_key, # Return detected key/tempo for consistency
            "detected_tempo": detected_tempo,
        }), 200

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request Error: {e}")
        return jsonify({"status": "error", "message": f"Failed to download audio or call external API: {e}"}), 500
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"status": "error", "message": f"An unexpected error occurred: {e}"}), 500
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir) # Clean up temporary files

if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", 5000))
