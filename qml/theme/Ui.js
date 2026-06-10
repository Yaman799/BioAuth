.pragma library

var DARK_FOUNDATION = {
    "isDark": true,
    "window": "#020913",
    "surface": "#071827",
    "surface0": "#051323",
    "surface1": "#0a1b2d",
    "surface2": "#0d2236",
    "surface3": "#091727",
    "surface4": "#0b1f33",
    "surface5": "#0b1b2d",
    "surface6": "#0c2135",
    "surface7": "#081827",
    "border": "#1d3b4b",
    "text": "#eaf3ff",
    "muted": "#9cafc9",
    "primary": "#0f9f9b",
    "primaryHover": "#14b8a6",
    "accent": "#22d3ee",
    "success": "#2dd4bf",
    "warn": "#d6a84f",
    "danger": "#fb7185",
    "info": "#22c7d8",
    "chipText": "#03121c",
    "glassBg": "#99081727",
    "glassBorder": "#24495d",
    "glassHighlight": "#33d8fbff",
    "neutralBg": "#13283b",
    "neutralHover": "#18344b",
    "neutralPressed": "#0d1e2d",
    "neutralBorder": "#25485a",
    "disabledBg": "#142234",
    "inputBg": "#cc091a2b",
    "chipBg": "#0a1d30",
    "chipSelectedBg": "#0f3447",
    "checkboxBg": "#0a1b2d",
    "checkboxHoverBg": "#0f2a40",
    "checkboxDisabledBg": "#132234",
    "switchOffBg": "#17283b",
    "progressTrackBg": "#102338",
    "trustPanel": "#06131f",
    "trustBezel": "#0a1d2f",
    "trustSurface": "#0d2235",
    "userCardBg": "#0c2135",
    "navActiveBg": "#0f2a40",
    "navIconBg": "#10283c",
    "warningBg": "#261f12",
    "dangerBg": "#2a1019",
    "iconActiveBg": "#0f2a3f",
    "overlayTint": "#6f06131f"
}

var LIGHT_FOUNDATION = {
    "isDark": false
}

function trx(isArabic, arText, enText) {
    return isArabic ? arText : enText
}

function paletteFor(theme) {
    return theme && theme.isDark === false ? LIGHT_FOUNDATION : DARK_FOUNDATION
}

function colorToken(theme, token) {
    var palette = paletteFor(theme)
    if (palette[token] !== undefined)
        return palette[token]
    if (theme && theme[token] !== undefined)
        return theme[token]
    return DARK_FOUNDATION[token] !== undefined ? DARK_FOUNDATION[token] : "#ffffff"
}

function foundationTheme(theme) {
    var merged = {}
    var key
    if (theme) {
        for (key in theme)
            merged[key] = theme[key]
    }
    var palette = paletteFor(theme)
    for (key in palette)
        merged[key] = palette[key]
    return merged
}

function toneColor(theme, tone) {
    if (tone === "success") return colorToken(theme, "success")
    if (tone === "warn" || tone === "warning") return colorToken(theme, "warn")
    if (tone === "danger" || tone === "error") return colorToken(theme, "danger")
    return colorToken(theme, "info")
}

function decisionTone(decision) {
    var v = String(decision || "").toLowerCase()
    if (v === "legit" || v === "authorized") return "success"
    if (v === "suspicious" || v === "warning") return "warn"
    if (v === "intruder" || v === "locked" || v === "blocked") return "danger"
    return "info"
}

function auraColor(theme, tone) {
    return toneColor(theme, tone)
}

function roleColor(theme, role) {
    if (role === "primary") return colorToken(theme, "primary")
    if (role === "success") return colorToken(theme, "success")
    if (role === "info") return colorToken(theme, "info")
    if (role === "warn" || role === "warning") return colorToken(theme, "warn")
    if (role === "danger" || role === "error") return colorToken(theme, "danger")
    if (role === "analyze") return theme && theme.isDark === false ? "#7c3aed" : "#6d5fd7"
    if (role === "details") return theme && theme.isDark === false ? "#0891b2" : "#22c7d8"
    return colorToken(theme, "neutralBg")
}

function roleHoverColor(theme, role) {
    if (role === "neutral") return colorToken(theme, "neutralHover")
    if (role === "info") return theme && theme.isDark === false ? "#0891b2" : "#2dd4e8"
    if (role === "success") return theme && theme.isDark === false ? "#16a34a" : "#34e0cd"
    if (role === "warn" || role === "warning") return theme && theme.isDark === false ? "#d97706" : "#e0b761"
    if (role === "analyze") return theme && theme.isDark === false ? "#8b5cf6" : "#7869e8"
    if (role === "details") return theme && theme.isDark === false ? "#22d3ee" : "#38d9e8"
    if (role === "primary") return colorToken(theme, "primaryHover")
    return roleColor(theme, role)
}

function rolePressedColor(theme, role) {
    if (role === "neutral") return colorToken(theme, "neutralPressed")
    if (role === "info") return theme && theme.isDark === false ? "#0e7490" : "#1596a6"
    if (role === "success") return theme && theme.isDark === false ? "#15803d" : "#14b8a6"
    if (role === "warn" || role === "warning") return theme && theme.isDark === false ? "#b45309" : "#b88a35"
    if (role === "analyze") return theme && theme.isDark === false ? "#6d28d9" : "#5a4bd1"
    if (role === "details") return theme && theme.isDark === false ? "#0891b2" : "#1596a6"
    if (role === "primary") return theme && theme.isDark === false ? colorToken(theme, "primaryHover") : "#0d827f"
    return roleColor(theme, role)
}

function roleBorderColor(theme, role) {
    if (role === "neutral") return colorToken(theme, "neutralBorder")
    if (role === "warn" || role === "warning") return theme && theme.isDark === false ? colorToken(theme, "warn") : "#8f733a"
    return roleColor(theme, role)
}

function roleTextColor(theme, role) {
    return role === "neutral" ? colorToken(theme, "text") : "#ffffff"
}
