from pydub import AudioSegment
import os

def convert_ogg_to_mp3(ogg_path: str) -> str:
    mp3_path = ogg_path.replace(".ogg", ".mp3")
    audio = AudioSegment.from_ogg(ogg_path)
    audio.export(mp3_path, format="mp3")
    return mp3_path