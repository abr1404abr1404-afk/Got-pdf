/* Set this to the HTTPS URL of your deployed Python OCR API. Leave empty to use browser OCR fallback. */
window.ALFALQI_API_BASE = "https://got-pdf.onrender.com";

/* OCR is processed locally in the browser by default to avoid Render Free CPU timeouts.
 * Set a separate HTTPS OCR endpoint here only after validating it on real Arabic scans.
 */
window.ALFALQI_OCR_API_BASE = "";

/*
 * Google Drive QR sharing is optional and remains unavailable until configured.
 * Set only the public OAuth Web Client ID here after completing SHARING_AND_ROADMAP.md.
 * Never place a Google OAuth Client Secret in this browser-side file.
 */
window.ALFALQI_GOOGLE_CLIENT_ID = "453331176505-rvfdb61fju5shka1s437j9hrcmgd62jd.apps.googleusercontent.com";
