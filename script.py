import os
import json
import mimetypes
import zipfile
from datetime import date
from io import BytesIO
from google import genai

import streamlit as st
from google import genai
from google.genai import types

# for PDF → image
from pdf2image import convert_from_bytes  # pip install pdf2image pillow
# for DOCX output
from docx import Document             # pip install python-docx
# for PDF output
from fpdf import FPDF                 # pip install fpdf

# ←── PAGE & THEME CONFIG ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Handwritten OCR",
    page_icon="🖋️",
    layout="centered",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
      :root {--primary-color:#004080;--bg-color:#f0f2f6;--sec-bg-color:#ffffff;--text-color:#333;}
      .main, .reportview-container {background-color:var(--bg-color)!important;color:var(--text-color)!important;}
      .block-container {padding:1.5rem 2rem!important;}
      h1 {font-size:3rem!important;color:var(--primary-color)!important;}
      h2 {font-size:2rem!important;color:var(--primary-color)!important;}
      .stMarkdown, .stText {font-size:18px!important;}
      .stTextArea>div>div>textarea {font-size:16px!important;}
      .stButton>button {
        background-color:var(--primary-color)!important;
        color:#fff!important;
        font-size:16px!important;
        padding:0.5rem 1rem!important;
      }
      .sidebar .sidebar-content {
        background-color:var(--sec-bg-color)!important;
        color:var(--text-color)!important;
        font-size:18px!important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ←── API & USAGE ───────────────────────────────────────────────────────────────
DEFAULT_API_KEY = " "
USAGE_FILE = "usage.json"
DAILY_LIMIT = 5

def guess_mime(fname: str) -> str:
    mime, _ = mimetypes.guess_type(fname)
    return mime or "application/octet-stream"

def ocr_with_gemini(client: genai.Client, data: bytes, fname: str, prompt: str) -> str:
    part = types.Part.from_bytes(data=data, mime_type=guess_mime(fname))
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[part, prompt],
    )
    return resp.text

def load_usage():
    if os.path.isfile(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            d = json.load(f)
    else:
        d = {"date": "", "count": 0}
    today = date.today().isoformat()
    if d.get("date") != today:
        d = {"date": today, "count": 0}
    return d

def save_usage(d):
    with open(USAGE_FILE, "w") as f:
        json.dump(d, f)

def make_pdf(text: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)
    for line in text.splitlines():
        pdf.multi_cell(0, 10, line)
    return pdf.output(dest="S").encode("latin1")

def make_docx(text: str) -> bytes:
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()

st.title("Handwritten to Text")

# --- sidebar: API key choice ---
st.sidebar.header("API Key")
choice = st.sidebar.radio("Use:", ["Default API (5/day)", "My own API (unlimited)"])
if choice == "My own API (unlimited)":
    api_key = st.sidebar.text_input("Enter your Gemini API key", type="password")
    # ←─ Display the “See how to btain API” link ───────────────
    st.sidebar.markdown(
        "[See how to btain API](https://aistudio.google.com/welcome?utm_source=google&utm_medium=cpc&utm_campaign=FY25-global-DR-gsem-BKWS-1710442&utm_content=text-ad-none-any-DEV_c-CRE_736651364289-ADGP_Hybrid%20%7C%20BKWS%20-%20EXA%20%7C%20Txt-Gemini%20(Growth)-Gemini%20API-KWID_43700081658580172-aud-2306308323534:kwd-927524447508&utm_term=KW_gemini%20api-ST_gemini%20api&gclsrc=aw.ds&gad_source=1&gad_campaignid=22307834138&gbraid=0AAAAACn9t65iHO0_47zIUOq2eMGR6hDYk&gclid=CjwKCAjwy7HEBhBJEiwA5hQNokXZKrt1lM-AB05JkkRfrvPLnPpju0SUQLHMyVWU25H5t8vfb3IXJxoCgwMQAvD_BwE)"
    )
    use_default = False
else:
    api_key = DEFAULT_API_KEY
    use_default = True

# --- input/output selectors ---
input_type = st.selectbox("Select input type:", ["Image", "PDF", "Word"])
output_type = st.selectbox("Select output format:", ["TXT", "PDF", "DOCX"])

# Only for PDF/Word, show a cautionary note
if input_type in ("PDF", "Word"):
    st.warning("Make sure your documents contain **pictures** of handwriting, _not_ embedded text.")

ext_map = {
    "Image": ["png", "jpg", "jpeg", "bmp"],
    "PDF":   ["pdf"],
    "Word":  ["docx"],
}
upload = st.file_uploader(f"Upload your {input_type} file", type=ext_map[input_type])

if upload and st.button("▶️ Convert"):
    if use_default:
        usage = load_usage()
        if usage["count"] >= DAILY_LIMIT:
            st.error(f"You’ve hit the {DAILY_LIMIT}/day limit with the default API.")
            st.stop()

    if not api_key:
        st.error("❗ Please enter a valid API key.")
        st.stop()

    client = genai.Client(api_key=api_key)
    prompt = (
        f"Please extract all handwritten text from this {input_type} exactly as it appears, "
        "without adding or removing anything."
    )

    with st.spinner("Running OCR…"):
        try:
            raw = upload.read()
            texts = []

            if input_type == "Image":
                texts.append(ocr_with_gemini(client, raw, upload.name, prompt))

            elif input_type == "PDF":
                pages = convert_from_bytes(raw, dpi=300)
                for i, page in enumerate(pages, start=1):
                    buf = BytesIO()
                    page.save(buf, format="PNG")
                    texts.append(ocr_with_gemini(client, buf.getvalue(), f"page-{i}.png", prompt))

            else:  # Word (.docx)
                z = zipfile.ZipFile(BytesIO(raw))
                imgs = [n for n in z.namelist() if n.startswith("word/media/")]
                if not imgs:
                    st.error("No embedded images found in the Word document.")
                    st.stop()
                for name in imgs:
                    img_bytes = z.read(name)
                    texts.append(ocr_with_gemini(client, img_bytes, os.path.basename(name), prompt))

            full_text = "\n\n--- Page Break ---\n\n".join(t.strip() for t in texts)

            if not full_text.strip():
                st.warning("⚠️ No text detected.")
            else:
                st.success("✅ Extracted text:")
                st.text_area("", full_text, height=250)

                # prepare output
                if output_type == "TXT":
                    data_out, ext, mime = full_text.encode("utf-8"), "txt", "text/plain"
                elif output_type == "PDF":
                    data_out, ext, mime = make_pdf(full_text), "pdf", "application/pdf"
                else:  # DOCX
                    data_out, ext, mime = make_docx(full_text), "docx", \
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

                st.download_button(
                    f"📥 Download .{ext}",
                    data=data_out,
                    file_name=f"output.{ext}",
                    mime=mime,
                )

                if use_default:
                    usage["count"] += 1
                    save_usage(usage)
                    st.info(f"✅ Default-API usage: {usage['count']}/{DAILY_LIMIT}")

        except Exception as e:
            st.error(f"❌ Error: {e}")
