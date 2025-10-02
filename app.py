from flask import Flask, request, jsonify
from supabase import create_client, Client
import os
import librosa
import soundfile as sf
from basic_pitch.inference import predict_and_save_midi
import numpy as np
# --- FIX: Missing requests import added here ---
import requests
import sys
import traceback

app = Flask(__name__)

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
# Ensure environment variables are present before trying to create a client
if not SUPABASE_URL or not SUPABASE_KEY:
    print("FATAL: SUPABASE_URL or SUPABASE_KEY environment variables are missing.")
    # In a real deployed app, this would be a hard stop, but Gunicorn needs the app object to exist.
    # We will initialize the client but rely on the error handling inside the route if it fails.
    supabase = None
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        supabase = None


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
    if not supabase:
        return jsonify({"error": "Supabase client not initialized due to missing environment variables."}), 500

    try:
        data = request.json
        audio_file_url = data.get("audio_file_url")
        user_id = data.get("user_id")
        audio_file_id = data.get("audio_file_id")
        desired_key = data.get("desired_key")
        desired_tempo = data.get("desired_tempo")

        # Download audio file from Supabase Storage
        # Assuming audio_file_url is a direct URL to the file in Supabase Storage
        response = requests.get(audio_file_url, stream=True)
        if response.status_code != 200:
            return jsonify({"error": f"Failed to download audio file. Status: {response.status_code}"}), 400

        local_audio_path = f"/tmp/temp_{audio_file_id}.wav" # Use /tmp for safe write access
        with open(local_audio_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        response.close() # Close the stream

        # Load audio
        # Using sr=None lets librosa determine the native sample rate
        y, sr = librosa.load(local_audio_path, sr=None) 

        # 1. Key and Tempo Detection (using librosa)
        estimated_tempo = librosa.beat.tempo(y=y, sr=sr)[0]
        estimated_key = "C Major" # Placeholder or use librosa.feature.tonnetz/chroma for analysis

        # 2. Pitch and Tempo Modification
        y_modified = y
        sr_modified = sr

        if desired_tempo and desired_tempo != estimated_tempo:
            speed_ratio = float(desired_tempo) / estimated_tempo
            y_modified = librosa.effects.time_stretch(y_modified, rate=speed_ratio)

        if desired_key and desired_key != estimated_key:
            semitone_shift = get_semitone_shift(estimated_key, desired_key)
            y_modified = librosa.effects.pitch_shift(y_modified, sr=sr_modified, n_steps=semitone_shift)

        # Save modified audio
        modified_audio_path = f"/tmp/modified_{audio_file_id}.wav"
        sf.write(modified_audio_path, y_modified, sr_modified)

        # 3. MIDI Data Extraction (using Basic-Pitch)
        midi_output_path = f"/tmp/midi_{audio_file_id}.mid"
        
        # NOTE: predict_and_save_midi expects a list of paths and saves output to output_dir.
        # We need to ensure the output directory is writable, so we'll use /tmp.
        # It also seems to save the file with a derived name, so we must find it or use the single-file method.
        # Let's use the standard predict() and write it manually for control.
        
        # Simple prediction run
        model_output, output_path_list = predict_and_save_midi(
            audio_path_list=[local_audio_path], 
            output_dir="/tmp/", 
            # We don't need a specific pm_path if we use the default output name logic
        ) 

        # Assuming Basic-Pitch names the MIDI file based on the audio name:
        base_name = os.path.splitext(os.path.basename(local_audio_path))[0]
        actual_midi_path = f"/tmp/{base_name}_basic_pitch.mid"
        
        # Fallback to the known output path if it was predictable (using the original name logic if you had a specific argument)
        if not os.path.exists(actual_midi_path) and output_path_list:
             actual_midi_path = output_path_list[0]
        
        # 4. Upload processed files to Supabase Storage
        
        # Upload Modified Audio
        storage_path_modified_audio = f"{user_id}/processed_audio/modified_{audio_file_id}.wav"
        with open(modified_audio_path, "rb") as f:
            supabase.storage.from_("processed-audio").upload(
                storage_path_modified_audio, 
                f.read(), 
                file_options={'content-type': 'audio/wav', 'upsert': 'true'}
            )

        # Upload MIDI
        storage_path_midi = f"{user_id}/processed_midi/midi_{audio_file_id}.mid"
        with open(actual_midi_path, "rb") as f:
            supabase.storage.from_("processed-midi").upload(
                storage_path_midi, 
                f.read(), 
                file_options={"content-type": "audio/midi", 'upsert': 'true'}
            )

        # 5. Clean up temporary files
        os.remove(local_audio_path)
        os.remove(modified_audio_path)
        if os.path.exists(actual_midi_path):
            os.remove(actual_midi_path)

        # 6. Return response
        return jsonify({
            "message": "Audio processed successfully",
            "modified_audio_url": f"{SUPABASE_URL}/storage/v1/object/public/processed-audio/{storage_path_modified_audio}",
            "midi_url": f"{SUPABASE_URL}/storage/v1/object/public/processed-midi/{storage_path_midi}"
        })

    except Exception as e:
        # Log the full traceback for debugging in Render logs
        print(f"An error occurred during audio processing: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return jsonify({"error": f"Internal Server Error: {str(e)}"}), 500

# The standard Gunicorn entry point does not rely on this block, but it's good practice.
# We removed the app.run() call from this block as Gunicorn handles running the server.
if __name__ == "__main__":
    print("WARNING: Running via __main__ is for local development only. Use Gunicorn for deployment.")
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
