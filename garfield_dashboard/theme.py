"""Shared visual constants for the Garfield dashboard."""

from __future__ import annotations

APP_TITLE = "Garfield Flagship"
APP_VERSION = "command dashboard"

COLORS = {
    "background": "#101112",
    "sidebar": "#151719",
    "surface": "#1A1D20",
    "surface_alt": "#23272B",
    "border": "#30363A",
    "text": "#F4F7FB",
    "text_secondary": "#A8B3C1",
    "accent": "#2DD4BF",
    "accent_hover": "#14B8A6",
    "accent_soft": "#123A38",
    "success": "#6EE7A8",
    "success_soft": "#143525",
    "warning": "#FBBF24",
    "warning_soft": "#3A2C12",
    "danger": "#FB7185",
    "danger_soft": "#3C1720",
    "muted": "#282C30",
    "input": "#111417",
}

FONTS = {
    "display": ("Segoe UI", 24, "bold"),
    "title": ("Segoe UI", 20, "bold"),
    "section": ("Segoe UI", 16, "bold"),
    "body": ("Segoe UI", 13),
    "body_bold": ("Segoe UI", 13, "bold"),
    "small": ("Segoe UI", 11),
    "mono": ("Consolas", 12),
}

TONE_COLOR = {
    "success": COLORS["success"],
    "warning": COLORS["warning"],
    "danger": COLORS["danger"],
    "info": COLORS["accent"],
    "muted": COLORS["text_secondary"],
}

TONE_BG = {
    "success": COLORS["success_soft"],
    "warning": COLORS["warning_soft"],
    "danger": COLORS["danger_soft"],
    "info": COLORS["accent_soft"],
    "muted": COLORS["muted"],
}
