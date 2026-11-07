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
    .main-card {
        background: #ffffff;
        padding: 20px;
        border-radius: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        margin-bottom: 16px;
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
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def split_into_sentences(text: str) -> list:
    """မြန်မာနှင့် အင်္ဂလိပ် စာကြောင်းများကို SRT အတွက် သဘာဝကျကျ ဖြတ်တောက်ခြင်း"""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks = []
    for line in raw_lines:
        # မြန်မာပုဒ်မ (။)၊ ပုဒ်ဖြတ် (၊) နှင့် အင်္ဂလိပ် (. ! ? ;) တို့ဖြင့် ခွဲထုတ်ခြင်း
        parts = re.split(r'(?<=[။.!?])\s*|(?<=၊)\s+', line)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # စာကြောင်းအရမ်းရှည်ပါက စာလုံးရေ ၈၀ စီ ထပ်ခွဲပေးခြင်း
            if len(p) > 85:
                sub_parts = [p[i:i+80].strip() for i in range(0, len(p), 80)]
                chunks.extend([sp for sp in sub_parts if sp])
            else:
                chunks.append(p)
    return chunks

async def generate_tts_and_srt(text: str, voice: str, speed_pct: int, pitch_pct: int, progress_bar):
    """
    ဝါကျအလိုက် အသံထုတ်ပြီး အသံအရှည်အတိအကျဖြင့် SRT Timestamp တွက်ချက်ပေးသည့် စနစ်
    (မြန်မာအသံများတွင် WordBoundary မရသည့် ပြဿနာကို ၁၀၀% ဖြေရှင်းပေးသည်)
    """
    rate_str = f"{speed_pct:+d}%"
    # Edge-TTS သည် pitch ကို Hz ဖြင့် လက်ခံသဖြင့် UI မှ -100%..+100% ကို -100Hz..+100Hz သို့ တိုက်ရိုက်ချိတ်ဆက်ပေးထားသည်
    pitch_str = f"{pitch_pct:+d}Hz"

    sentences = split_into_sentences(text)
    if not sentences:
        return b"", ""

    combined_audio = bytearray()
    srt_entries = []
    current_time = 0.0
    total = len(sentences)

    for idx, sentence in enumerate(sentences, start=1):
        communicate = edge_tts.Communicate(
            text=sentence,
            voice=voice,
            rate=rate_str,
            pitch=pitch_str
        )

        sentence_audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                sentence_audio.extend(chunk["data"])

        # အသံဖိုင်၏ ကြာချိန်အတိအကျကို Mutagen ဖြင့် တိုင်းတာခြင်း
        duration = 0.0
        if sentence_audio:
            try:
                audio_io = io.BytesIO(bytes(sentence_audio))
                mp3_info = MP3(audio_io)
                duration = mp3_info.info.length
            except Exception:
                # အကယ်၍ header ဖတ်မရပါက စာလုံးအရေအတွက်ဖြင့် ခန့်မှန်းချိန်တွက်ခြင်း
                duration = max(1.2, len(sentence) * 0.12)

            combined_audio.extend(sentence_audio)

            start_ts = format_srt_time(current_time)
            end_ts = format_srt_time(current_time + duration)
            srt_entries.append(f"{idx}\n{start_ts} --> {end_ts}\n{sentence}\n")
            current_time += duration

        progress_bar.progress(idx / total, text=f"အသံနှင့် SRT ထုတ်နေပါသည်... ({idx}/{total})")

    srt_content = "\n".join(srt_entries)
    return bytes(combined_audio), srt_content

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
        # Edge-TTS တွင် -100% အတိအကျပို့လျှင် API Error တက်တတ်သဖြင့် -99% သို့ အလိုအလျောက် ညှိပေးထားသည်
        safe_speed = -99 if speed_val == -100 else speed_val
        safe_pitch = -99 if pitch_val == -100 else pitch_val

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
                st.error("အသံထုတ်ရာတွင် အမှားအယွင်းရှိနေပါသည်။ စာသားပြန်စစ်ပေးပါ။")
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
