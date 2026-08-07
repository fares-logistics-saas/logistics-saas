import streamlit as st

st.set_page_title("Pricing - Logistics SaaS")
st.title("💰 Pricing Plans")

st.write("Choose the right plan for your logistics business.")

col1, col2 = st.columns(2)

with col1:
  st.subheader("Starter Plan")
  st.write("**$29 / month**")
  st.write("Basic invoice auditing and database logging.")

with col2:
  st.subheader("Enterprise Plan")
  st.write("**$99 / month**")
  st.write("Unlimited high-speed batch processing and strict contract auditing.")
