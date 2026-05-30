"""Centralized X DOM selectors.

X's UI changes often; all selectors live here so perception modules have one
maintenance surface and can fall back to vision when DOM extraction breaks.
"""

X_HOME_URL = "https://x.com/home"
X_LOGIN_URL = "https://x.com/i/flow/login"

TWEET_ARTICLE = "article[data-testid='tweet']"
TWEET_TEXT = "[data-testid='tweetText']"
LIKE_COUNT = "[data-testid='like']"
RETWEET_COUNT = "[data-testid='retweet']"
REPLY_COUNT = "[data-testid='reply']"
TREND_ITEM = "[data-testid='trend']"
