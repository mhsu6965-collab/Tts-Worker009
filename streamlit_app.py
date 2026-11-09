import streamlit as st
import edge_tts
import asyncio
import re
import io
from mutagen.mp3 import MP3

# --- Page Configuration ---
st.set_page_config(
    page_title="Edge-TTS & SRT Generator",
    page_icon="🎙️",
    layout="centered"
)

# --- Light & Mobile-Friendly Custom CSS ---
st.markdown("""
<style>
    .stApp {
        background-color: #f8fafc;
        color: #1e293b;
    }
    .char-counter {
        font-weight: 600;
        font-size: 0.95rem;
        padding: 6px 12px;
        border-radius: 8px;
        display: inline-block;
        margin-bottom: 10px;
    }
    .char-ok {
        background-color: #e0f2fe;
        color: #0369a1;
    }
    .char-over {
        background-color: #fee2e2;
        color: #b91c1c;
    }
    div.stButton > button {
        width: 100%;
        border-radius: 10px;
        font-weight: 600;
        padding: 0.6rem 1rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎙️ Microsoft Edge TTS & SRT Generator")
st.caption("အသံဖိုင် (MP3) နှင့် အသံချိန်ကိုက် Subtitle (SRT) ထုတ်ပေးသည့် Web App (စာလုံးရေ ၂၀,၀၀၀ အထိ)")

# --- Voice List ---
VOICES = {
    "🇲🇲 မြန်မာ - နီလာ (Nilar - အမျိုးသမီး)": "my-MM-NilarNeural",
    "🇲🇲 မြန်မာ - သီဟ (Thiha - အမျိုးသား)": "my-MM-ThihaNeural",
    "🇺🇸 English (US) - Aria (Female)": "en-US-AriaNeural",
    "🇺🇸 English (US) - Guy (Male)": "en-US-GuyNeural",
    "🇺🇸 English (US) - Jenny (Female)": "en-US-JennyNeural",
    "🇬🇧 English (UK) - Sonia (Female)": "en-GB-SoniaNeural",
    "🇹🇭 Thai - Premwadee (Female)": "th-TH-PremwadeeNeural",
    "🇹🇭 Thai - Niwat (Male)": "th-TH-NiwatNeural",
    "🇨🇳 Chinese - Xiaoxiao (Female)": "zh-CN-XiaoxiaoNeural",
    "🇨🇳 Chinese - Yunxi (Male)": "zh-CN-YunxiNeural",
    "🇯🇵 Japanese - Nanami (Female)": "ja-JP-NanamiNeural",
    "🇰🇷 Korean - SunHi (Female)": "ko-KR-SunHiNeural",
}

MAX_CHARS = 20000

# --- Helper Functions ---
def format_srt_time(seconds: float) -> str:
    """စက္ကန့်ကို SRT အချိန်ဖော်မတ် (HH:MM:SS,mmm) သို့ ပြောင်းပေးခြင်း"""
    if seconds < 0:
        seconds = 0
    millis = int(round((seconds % 1) * 1000))
    total_seconds = int(seconds)
    mins, secs = divmod(total_seconds, 60)
    hrs, mins = divmod(mins, 60)
    if millis == 1000:
        secs += 1
        millis = 0
        if secs == 60:
            mins += 1
            secs = 0
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def has_speakable_text(text: str) -> bool:
    """အသံထွက်နိုင်သော စာလုံး (မြန်မာ/အင်္ဂလိပ်/ဂဏန်း) ပါမပါ စစ်ဆေးခြင်း"""
    # သင်္ကေတနှင့် Space များဖယ်ပြီး စာလုံးကျန်မကျန် စစ်သည်
    cleaned = re.sub(r'[\s\W_]+', '', text, flags=re.UNICODE)
    # မြန်မာသရ/ဗျည်း နှင့် အခြားစာလုံးများ ပါဝင်မှု စစ်ဆေးခြင်း
    if cleaned or re.search(r'[\u1000-\u109F\uAA60-\uAA7F\w]', text):
        # ပုဒ်မ (။)၊ ပုဒ်ဖြတ် (၊) သက်သက်သာ ဖြစ်နေလျှင် ပယ်ဖျက်မည်
        only_stripped = re.sub(r'[။၊"\'“”‘’()\[\]{}.,!?;\-—_…\s]+', '', text)
        return len(only_stripped) > 0
    return False

def clean_text_for_tts(text: str) -> str:
    """Edge-TTS တွင် Error တက်စေသော အထူးသင်္ကေတများကို သန့်စင်ခြင်း"""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('<', ' ').replace('>', ' ').replace('&', ' and ')
    return re.sub(r'\s+', ' ', text).strip()

def split_into_srt_lines(text: str) -> list:
    """SRT စာတန်းထိုးအတွက် ဝါကျတိုများအဖြစ် သဘာဝကျကျ ခွဲထုတ်ခြင်း"""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentences = []
    for line in raw_lines:
        parts = re.split(r'(?<=[။.!?])\s*|(?<=၊)\s+', line)
        for p in parts:
            p = clean_text_for_tts(p)
            if not has_speakable_text(p):
                continue
            if len(p) > 85:
                sub_parts = [p[i:i+80].strip() for i in range(0, len(p), 80)]
                for sp in sub_parts:
                    if has_speakable_text(sp):
                        sentences.append(sp)
            else:
                sentences.append(p)
    return sentences

def group_sentences_ into_batches(sentences: list, max_batch_chars: int = 450) -> list:
    """
    Request အရေအတွက် နည်းစေရန်နှင့် မြန်ဆန်စေရန် ဝါကျများကို အုပ်စုဖွဲ့ခြင်း (Batching)
    """
    batches = []
    current_batch = []
    current_len = 0

    for s in sentences:
        if current_len + len(s) > max_batch_chars and current_batch:
            batches.append(current_batch)
            current_batch = [s]
            current_len = len(s)
        else:
            current_batch.append(s)
            current_len += len(s)

    if current_batch:
        batches.append(current_batch)
    return batches

async def fetch_audio_with_retry(text: str, voice: str, rate_str: str, pitch_str: str, retries: int = 3) -> bytes:
    """NoAudioReceived မဖြစ်စေရန် Auto-Retry နှင့် Fallback ပါဝင်သော Function"""
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate_str,
                pitch=pitch_str
            )
            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
            if audio_data:
                return bytes(audio_data)
        except Exception:
            if attempt < retries - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
            else:
                # နောက်ဆုံးအကြိမ်တွင် pitch/rate မပါဘဲ Default ဖြင့် ထပ်စမ်းပေးခြင်း
                try:
                    comm_fallback = edge_tts.Communicate(text=text, voice=voice)
                    audio_data = bytearray()
                    async for chunk in comm_fallback.stream():
                        if chunk["type"] == "audio":
                            audio_data.extend(chunk["data"])
                    if audio_data:
                        return bytes(audio_data)
                except Exception:
                    return b""
    return b""

async def generate_tts_and_srt(text: str, voice: str, speed_pct: int, pitch_pct: int, progress_bar):
    rate_str = f"{speed_pct:+d}%"
    pitch_str = f"{pitch_pct:+d}Hz"

    sentences = split_into_srt_lines(text)
    if not sentences:
        return b"", ""

    batches = group_sentences_into_batches(sentences, max_batch_chars=450)
    combined_audio = bytearray()
    srt_entries = []
    current_time = 0.0
    srt_index = 1
    total_batches = len(batches)

    for b_idx, batch_sentences in enumerate(batches, start=1):
        batch_text = " ".join(batch_sentences)
        batch_audio = await fetch_audio_with_retry(batch_text, voice, rate_str, pitch_str)

        if batch_audio:
            try:
                audio_io = io.BytesIO(batch_audio)
                mp3_info = MP3(audio_io)
                batch_duration = mp3_info.info.length
            except Exception:
                batch_duration = max(1.5, len(batch_text) * 0.11)

            combined_audio.extend(batch_audio)

            # Batch အတွင်းရှိ ဝါကျတစ်ခုချင်းစီ၏ စာလုံးအချိုးအစားအလိုက် SRT အချိန်ကို အတိအကျ ခွဲဝေပေးခြင်း
            total_Batch_chars = sum(max(1, len(s)) for s in batch_sentences)
            for s in batch_sentences:
                weight = max(1, len(s)) / total_Batch_chars
                s_duration = batch_duration * weight
                start_ts = format_srt_time(current_time)
                end_ts = format_srt_time(current_time + s_duration)
                srt_entries.append(f"{srt_index}\n{start_ts} --> {end_ts}\n{s}\n")
                current_time += s_duration
                srt_index += 1

        progress_bar.progress(
            b_idx / total_batches,
            text=f"အသံနှင့် SRT ထုတ်နေပါသည်... ({int((b_idx / total_batches) * 100)}%)"
        )
        # Server Rate-limit မထိစေရန် ခေတ္တနားပေးခြင်း
        await asyncio.sleep(0.15)

    return bytes(combined_audio), "\n".join(srt_entries)

# --- UI Controls ---
with st.container():
    selected_voice_label = st.selectbox("🗣️ အသံရွေးချယ်ပါ (Select Voice)", list(VOICES.keys()))
    selected_voice = VOICES[selected_voice_label]

    col1, col2 = st.columns(2)
    with col1:
        speed_val = st.slider(
            "⚡ Speed (အမြန်နှုန်း %)",
            min_value=-100,
            max_value=100,
            value=0,
            step=5,
            format="%d%%"
        )
        st.caption(f"လက်ရှိ Speed: **{speed_val:+d}%**")

    with col2:
        pitch_val = st.slider(
            "🎵 Pitch (အသံအနိမ့်အမြင့် %)",
            min_value=-100,
            max_value=100,
            value=0,
            step=5,
            format="%d%%"
        )
        st.caption(f"လက်ရှိ Pitch: **{pitch_val:+d}%**")

# --- Text Input & Character Limit (20,000) ---
text_input = st.text_area(
    "📝 အသံပြောင်းလိုသော စာသားထည့်ပါ (အများဆုံး စာလုံးရေ ၂၀,၀၀၀)",
    height=260,
    max_chars=MAX_CHARS,
    placeholder="ဒီနေရာမှာ စာသားရိုက်ထည့်ပါ (သို့မဟုတ်) Paste လုပ်ပါ..."
)

char_count = len(text_input)
if char_count <= MAX_CHARS:
    st.markdown(
        f'<div class="char-counter char-ok">စာလုံးရေ: {char_count:,} / {MAX_CHARS:,}</div>',
        unsafe_allow_html=True
    )
else:
    st.markdown(
        f'<div class="char-counter char-over">⚠️ စာလုံးရေ ကန့်သတ်ချက် ကျော်လွန်နေပါသည်: {char_count:,} / {MAX_CHARS:,}</div>',
        unsafe_allow_html=True
    )

# --- Generate Button ---
if st.button("🚀 အသံဖိုင် (MP3) နှင့် SRT ထုတ်မည်", type="primary"):
    if not text_input.strip():
        st.warning("ကျေးဇူးပြု၍ အသံပြောင်းလိုသော စာသားအရင်ထည့်ပါ။")
    elif char_count > MAX_CHARS:
        st.error(f"စာလုံးရေ {MAX_CHARS:,} ထက် ကျော်လွန်နေပါသည်။ စာသားအချို့ လျှော့ချပေးပါ။")
    else:
        # Edge-TTS သည် -90% အောက် သို့မဟုတ် ±100% တွင် NoAudioReceived ပြတတ်သဖြင့် Safe Range သို့ ထိန်းပေးထားသည်
        safe_speed = max(-90, min(100, speed_val))
        safe_pitch = max(-90, min(100, pitch_val))

        progress = st.progress(0, text="စတင်နေပါသည်...")
        try:
            audio_bytes, srt_text = asyncio.run(
                generate_tts_and_srt(
                    text=text_input,
                    voice=selected_voice,
                    speed_pct=safe_speed,
                    pitch_pct=safe_pitch,
                    progress_bar=progress
                )
            )
            progress.empty()

            if audio_bytes:
                st.session_state["tts_audio"] = audio_bytes
                st.session_state["tts_srt"] = srt_text
                st.success("✅ အသံဖိုင်နှင့် SRT Subtitle ဖိုင် ထုတ်ပြီးပါပြီ!")
            else:
                st.error("အသံထုတ်မရပါ။ Streamlit Cloud မှ Reboot App လုပ်ပြီး ပြန်စမ်းကြည့်ပါ။")
        except Exception as e:
            progress.empty()
            st.error(f"Error ဖြစ်ပွားပါသည်: {e}")

# --- Output & Download Section ---
if "tts_audio" in st.session_state and st.session_state["tts_audio"]:
    st.markdown("---")
    st.subheader("🎧 နားထောင်ရန်နှင့် ဒေါင်းလုဒ်ဆွဲရန်")
    st.audio(st.session_state["tts_audio"], format="audio/mp3")

    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        st.download_button(
            label="📥 MP3 အသံဖိုင် ဒေါင်းရန်",
            data=st.session_state["tts_audio"],
            file_name="edge_tts_audio.mp3",
            mime="audio/mpeg"
        )
    with dl_col2:
        st.download_button(
            label="📥 SRT Subtitle ဖိုင် ဒေါင်းရန်",
            data=st.session_state["tts_srt"].encode("utf-8"),
            file_name="edge_tts_subtitle.srt",
            mime="text/plain"
        )

    with st.expander("📄 ထွက်ရှိလာသော SRT Subtitle အကြိုကြည့်ရန် (Preview)"):
        st.text_area("SRT Content", value=st.session_state["tts_srt"], height=220)
