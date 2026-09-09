# Privacy and data handling

## 1. Overview
Whatte processes personal training data to provide deterministic training-load,
readiness, and recommendation support. It is a single-user prototype; this file
describes the repository's intended handling, not a contractual privacy notice.

## 2. Data we collect
- Training data (e.g. cycling activities from Strava)
- Historical physiology records (heart rate, HRV, sleep, and weight) that were
  collected before the HealthKit path was retired
- User-provided FTP, weight, and subjective feedback (post-ride RPE and
  next-day recovery)

## 3. How data is used
Data is used to:
- calculate training load and readiness
- generate deterministic recommendation and briefing output
- provide analytics and insights

## 4. Data storage
The active runtime stores data on infrastructure controlled by the project
owner. Raw Strava payloads and historical physiology records are retained for
reproducibility. HealthKit collection and the iOS client are retired; no active
HealthKit collection endpoint exists.

## 5. Data sharing
The application does not sell or disclose stored data to third parties. Strava,
Telegram, and hosting providers process the requests needed for their respective
integrations under their own terms.

## 6. User control
The operator can remove a user's stored data on request. Do not put secrets,
tokens, raw personal payloads, or production database dumps in Git, issue
reports, or documentation.

## 7. Disclaimer
This project is not a medical service and does not provide medical advice.
