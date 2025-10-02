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
    try:
        data = request.json
        audio_file_url = data.get("audio_file_url")
        user_id = data.get("user_id")
        audio_file_id = data.get("audio_file_id")
        desired_key = data.get("desired_key")
        desired_tempo = data.get("desired_tempo")

        if not all([audio_file_url, user_id, audio_file_id]):
            return jsonify({"status": "error", "message": "Missing required parameters"}), 400

        # Create a temporary directory for processing
        with tempfile.TemporaryDirectory() as tmpdir:
            local_audio_path = os.path.join(tmpdir, "input_audio.wav")
            processed_audio_path = os.path.join(tmpdir, "processed_audio.wav")
            midi_output_dir = os.path.join(tmpdir, "midi_output")
            os.makedirs(midi_output_dir, exist_ok=True)

            # --- 1. Download Audio File from Supabase Storage ---
            response = requests.get(audio_file_url, stream=True)
            response.raise_for_status() # Raise an exception for HTTP errors
            with open(local_audio_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # --- 2. Audio Analysis (Key & Tempo Detection via SoundStat.info) ---
            detected_key = None
            detected_tempo = None
            if SOUNDSTAT_API_URL and SOUNDSTAT_API_KEY:
                try:
                    with open(local_audio_path, "rb") as f_audio:
                        soundstat_response = requests.post(
                            SOUNDSTAT_API_URL,
                            headers={
                                "Authorization": f"Bearer {SOUNDSTAT_API_KEY}",
                                "Content-Type": "audio/wav"
                            },
                            data=f_audio
                        )
                    soundstat_response.raise_for_status()
                    analysis_results = soundstat_response.json()
                    # Assuming SoundStat.info returns 'key' and 'tempo' directly
                    detected_key = analysis_results.get("key")
                    detected_tempo = analysis_results.get("tempo")
                    print(f"SoundStat Analysis: Key={detected_key}, Tempo={detected_tempo}")
                except requests.exceptions.RequestException as e:
                    print(f"SoundStat API call failed: {e}")
                except Exception as e:
                    print(f"Error parsing SoundStat response: {e}")

            # --- 3. Audio Modification (Pitch Shifting & Time Stretching) ---
            y, sr = librosa.load(local_audio_path, sr=None) # Load audio with original sample rate
            modified_y = y
            modified_sr = sr
            processed_audio_url = None

            # Pitch Shifting
            if desired_key and detected_key: # Only shift if a desired key and detected key are available
                semitone_shift = get_semitone_shift(detected_key, desired_key)
                if semitone_shift != 0:
                    modified_y = librosa.effects.pitch_shift(y=modified_y, sr=sr, n_steps=semitone_shift)
                    print(f"Pitch shifted by {semitone_shift} semitones.")

            # Time Stretching (Tempo Modification)
            if desired_tempo and detected_tempo: # Only stretch if a desired tempo and detected tempo are available
                tempo_ratio = desired_tempo / detected_tempo
                if tempo_ratio != 1.0:
                    modified_y = librosa.effects.time_stretch(y=modified_y, rate=tempo_ratio)
                    print(f"Time stretched by ratio {tempo_ratio}.")

            # Save processed audio if any modification occurred
            if np.array_equal(y, modified_y) == False: # Check if audio was actually modified
                sf.write(processed_audio_path, modified_y, modified_sr)
                # Upload processed audio to Supabase Storage
                with open(processed_audio_path, "rb") as f:
                    storage_path = f"processed_audio/{user_id}/{audio_file_id}_processed.wav"
                    # CORRECTED LINE HERE
                    supabase.storage.from("processed-audio").upload(storage_path, f, file_options={"contentType": "audio/wav"})
                    processed_audio_url = supabase.storage.from("processed-audio").get_public_url(storage_path)
                    print(f"Processed audio uploaded to: {processed_audio_url}")

            # --- 4. Audio to MIDI Conversion (Basic-Pitch) ---
            midi_file_url = None
            try:
                # Basic-Pitch expects a list of audio paths
                predict_and_save_midi(audio_path_list=[local_audio_path], output_dir=midi_output_dir)
                midi_filename = os.path.join(midi_output_dir, os.listdir(midi_output_dir)[0]) # Assuming one MIDI file generated

                with open(midi_filename, "rb") as f:
                    storage_path = f"midi_files/{user_id}/{audio_file_id}.mid"
                    supabase.storage.from("midi-files").upload(storage_path, f, file_options={"contentType": "audio/midi"})
                    midi_file_url = supabase.storage.from("midi-files").get_public_url(storage_path)
                    print(f"MIDI file uploaded to: {midi_file_url}")
            except Exception as e:
                print(f"Error during MIDI conversion or upload: {e}")

            # --- 5. Update Supabase Database with Results ---
            update_data = {
                "status": "analyzed",
                "detected_key": detected_key,
                "detected_tempo": detected_tempo,
            }
            if processed_audio_url:
                update_data["processed_audio_url"] = processed_audio_url
                update_data["status"] = "modified" # Update status if modified audio is present
            if midi_file_url:
                update_data["midi_file_url"] = midi_file_url

            response_db = supabase.table("audio_files").update(update_data).eq("id", audio_file_id).execute()
            response_db.raise_for_status()
            print(f"Database updated for audio_file_id: {audio_file_id}")

            return jsonify({
                "status": "success",
                "message": "Audio processed successfully",
                "detected_key": detected_key,
                "detected_tempo": detected_tempo,
                "processed_audio_url": processed_audio_url,
                "midi_file_url": midi_file_url
            }), 200

    except requests.exceptions.RequestException as e:
        print(f"HTTP Request Error: {e}")
        return jsonify({"status": "error", "message": f"External service error: {e}"}), 500
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return jsonify({"status": "error", "message": f"An unexpected error occurred: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=os.environ.get("PORT", 5000))
