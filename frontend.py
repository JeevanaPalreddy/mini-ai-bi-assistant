"""Streamlit frontend. Talks to the FastAPI backend only."""

import os

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

EXAMPLES = [
    "Total revenue",
    "Top 3 products by revenue",
    "Monthly revenue trend",
    "Average order value by region",
    "How many orders per sales channel?",
]

st.set_page_config(page_title="Mini AI BI Assistant", page_icon="📊")
st.title("📊 Mini AI BI Assistant")
st.caption("Ask a question about the sales data. Only Completed orders count toward revenue.")

if "question" not in st.session_state:
    st.session_state["question"] = ""


def set_question(text: str) -> None:
    st.session_state["question"] = text


st.write("Try an example:")
for example in EXAMPLES:
    st.button(example, on_click=set_question, args=(example,), key=f"ex_{example}")

question = st.text_input("Your question", key="question", max_chars=500)

if st.button("Ask", type="primary"):
    if not question.strip():
        st.warning("Please type a question first.")
    else:
        try:
            with st.spinner("Working on it..."):
                resp = requests.post(f"{API_URL}/ask", json={"question": question}, timeout=30)
        except requests.exceptions.ConnectionError:
            st.error("Cannot reach the backend. Start it with: uvicorn app.main:app --port 8000")
            st.stop()
        except requests.exceptions.Timeout:
            st.error("The backend took too long to respond. Please try again.")
            st.stop()

        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", "Unknown error")
            except ValueError:
                detail = "Unknown error"
            if isinstance(detail, list):
                detail = "The question is invalid (1 to 500 characters)."
            st.error(f"Request failed ({resp.status_code}): {detail}")
            st.stop()

        data = resp.json()
        label = "AI (Claude)" if data["interpreted_by"] == "llm" else "Rule-based fallback"
        st.caption(f"Interpreted by: **{label}**")
        if data.get("notice"):
            st.info(data["notice"])
        st.subheader(data["description"])

        if data["rows"]:
            df = pd.DataFrame(data["rows"])
            if data["spec"]["group_by"] is None:
                st.metric(data["rows"][0]["label"], f"{df['value'].iloc[0]:,.2f}")
            else:
                chart = df.set_index("label")["value"]
                if data["spec"]["group_by"] == "order_month":
                    st.line_chart(chart)
                else:
                    st.bar_chart(chart)
                st.dataframe(df.rename(columns={"label": "Group", "value": "Value"}), hide_index=True)
                if data.get("total") is not None:
                    st.caption(f"Overall total for this filter: {data['total']:,.2f}")
        with st.expander("How the question was understood"):
            st.json(data["spec"])