# Internal Telesales Call Analysis Dashboard

Live dashboard showing call analysis for "Not Interested" outcomes.

## Features
- **Ireland Overview**: All Ireland calls with filtering by red flag issues
- **UK Overview**: All UK calls with filtering by red flag issues  
- **Individual Analysis**: Per-agent performance with trending analysis
- **Yesterday's Calls**: Quick view of most recent calls

## Auto-Updates

This dashboard automatically updates in two ways:

1. **When you edit the HTML**: Push changes to `main` branch → auto-deploys to GitHub Pages
2. **Every 15 minutes**: Checks for new "Not Interested" calls → analyzes them → updates the dashboard

## Manual Trigger

You can manually trigger the call analysis from the Actions tab → "Analyze New Calls" → "Run workflow"

## Data Source

Data comes from: [Adversus API Google Sheet](https://docs.google.com/spreadsheets/d/1Y8nHFCR5hqEwqjurcYjMob3IyAHoO4pp9uDcazwSIuQ)
