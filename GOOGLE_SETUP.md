# Google Custom Search API Setup Guide

To enable Google Custom Search in your QA Chat app, follow these steps:

## 1. Set Up Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Custom Search API**:
   - Go to **APIs & Services** > **Library**
   - Search for "Custom Search API"
   - Click on it and press **Enable**

## 2. Create API Key

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **API Key**
3. Copy the API key (you'll need it in the next step)

## 3. Create a Custom Search Engine

1. Go to [Google Custom Search Control Panel](https://cse.google.com/cse/all)
2. Click **Create** to create a new search engine
3. Enter a name and the sites you want to search (or leave empty to search the entire web)
4. Create the search engine
5. In the search engine settings, find your **Search Engine ID (CX)**
6. Copy this ID

## 4. Set Environment Variables

Set these environment variables before running the app:

```bash
export GOOGLE_API_KEY="your-api-key-here"
export GOOGLE_SEARCH_ENGINE_ID="your-search-engine-id-here"
```

Or create a `.env` file in the project directory:

```
GOOGLE_API_KEY=your-api-key-here
GOOGLE_SEARCH_ENGINE_ID=your-search-engine-id-here
```

Then load it before running:

```bash
source .env
streamlit run app.py
```

## 5. Install Dependencies

Install the required package:

```bash
pip install -r requirements.txt
```

## Important Notes

- **Free Tier**: Google Custom Search offers 100 free queries per day
- **Quota**: After exceeding free tier, you need to enable billing
- **Fallback**: If API credentials are missing or quota is exceeded, the app will gracefully fall back to Wikipedia and DuckDuckGo
- **Search Coverage**: With Google Custom Search enabled, you can now answer queries about:
  - Sports, politics, news
  - Books, movies, games
  - Countries, capitals, geography
  - Recent events and trending topics

## Testing

After setup, try these queries:
- "Who is Joe Biden?"
- "What is the plot of Harry Potter?"
- "What is Machine Learning?"
- "Capital of France"
- "Latest technology news"

## Troubleshooting

- **"API key is invalid"**: Check that you copied the key correctly from Google Cloud Console
- **"Search engine ID not found"**: Verify your CX ID from the Custom Search Control Panel
- **No results**: Increase the `num` parameter in `fetch_google_answer()` or adjust your search engine configuration
- **Rate limit errors**: This means you've exceeded your daily quota. Upgrade to a paid plan or wait for the quota to reset
