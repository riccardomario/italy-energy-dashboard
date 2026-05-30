"""Simple shared-password gate for the dashboard."""

import streamlit as st


def check_password() -> bool:
    """Return True if the user is authenticated. Renders a password prompt if not.

    Call at the top of every page. Authentication persists in session_state, so
    the user only types the password once per browser session.
    """
    if st.session_state.get("auth_ok"):
        return True

    st.title("Italy Energy Dashboard")
    pwd = st.text_input("Password", type="password", key="_pwd_input")
    if pwd:
        expected = st.secrets.get("DASHBOARD_PASSWORD")
        if expected and pwd == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False
