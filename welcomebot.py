from argparse import ArgumentParser
import logging
from mastodon import Mastodon
from os import environ
from time import sleep

class WelcomeBot():
    """
    The WelcomeBot application.

    This uses the hashtag timeline API to effectively "watch" a hashtag. There are other ways to find toots with a certain hashtag. The web push API seems really promising. 
    The assumption behind not taking the push based approach is that it will cost more to have a server running constantly. 
    It's also harder to replay or backfill using the streaming API. Yeah, polling plus pagination is unsexy, but it works.
    
    There are a number of limitations with the current approach (in no particular order):
    1. Ideally we'd like to be able to watch multiple hashtags. Doing this creates a few edge cases. We would need to deduplicate if people use multiple hashtags in the same toot.
    It would also be nice to do them in order regardless of what hashtag their using.
    2. There are no retries
    3. There's no parallelism
    4. It's totally synchronous (limit of the client)
    5. There's no functionality to check on our AWS lambda timeout. It would be nice to be able to take bite sized pieces and delay any work that would potentially put us over our time limit.
    6. We don't deduplicate which users have been introduced before (could get spammy). This would require some way to store state.
    """

    def __init__(self, client, logger, batch_size = 20, dry_run = False):
        """
        Creates a new welcome bot instance. See get_or_create for a lazy singleton approach to initialization
        """
        self.logger = logger
        self.client = client
        self.batch_size = batch_size
        self.dry_run = dry_run

    def is_tootable(self, toot):
        """
        Checks that the toot is public.
        Also checks that the toot is not a reply or retoot
        """
        return toot["visibility"] == "public" and \
            toot["reblog"] is None and \
            toot["in_reply_to_id"] is None and \
            toot["in_reply_to_account_id"] is None

    def retoot_batch(self, hashtag, since_id, max_id = None):
        """
        Retoots a given batch of toots the newest n toots after since_id but before max_id
        """
        logger.debug("Attempting to fetch %s toots", self.batch_size)
        toots = self.client.timeline_hashtag(hashtag, since_id = since_id, max_id = max_id, local = True, limit = self.batch_size)
        batch_len = len(toots)
        if batch_len == 0:
            return (since_id, since_id, batch_len)
        oldest_id = toots[-1]["id"]
        latest_id = toots[0]["id"]
        logger.info("Got %s toots", batch_len)
        logger.debug("Most recent toot is \"%s\"", latest_id)
        for toot in toots:
            logger.info("Saw toot \"%s\"", toot["id"])
            logger.debug("Full toot %s", toot)
            if self.is_tootable(toot):
                if not self.dry_run:
                    logger.info("Retooting toot \"%s\"", toot["id"])
                    self.client.status_reblog(toot["id"])
                else:
                    logger.info("Would have retooted toot \"%s\"", toot["id"])


        return (oldest_id, latest_id, batch_len)
        

    def retoot_intros(self, hashtag, since_id):
        """
        Retoots each toot for the given hashtag since a given id
        It starts with the most recent and works it's way backwards.
        """
        logger.info("Retooting with hashtag \"%s\" since the id \"%s\"", hashtag, since_id)
        
        (max_id, latest_id, batch_len) = self.retoot_batch(hashtag, since_id)
        while True:
            if batch_len < self.batch_size:
                logger.info("Done with all toots. Started at \"%s\" finished at \"%s\".", since_id, latest_id)
                return latest_id
            (max_id, _, batch_len) = self.retoot_batch(hashtag, since_id, max_id)

    def get_most_recent_id(self, hashtag):
        logger.info("Getting most recent toot for hashtag \"%s\"", hashtag)
        toots = self.client.timeline_hashtag(hashtag, local = True, limit = 1)
        if len(toots) == 0:
            logger.info("Found no toots")
            return None
        else:
            logger.info("Most recent toot is \"%s\"", toots[-1]["id"])
            logger.debug("Full toot %s", toots[-1])
            return toots[0]["id"]

def collect_env_vars():
    """
    Collects the necessary parameters from the environment or explodes

    These are:
    WELCOME_BOT_API_BASE_URL
    WELCOME_BOT_USERNAME
    WELCOME_BOT_PASSWORD
    WELCOME_BOT_CLIENT_SECRET
    WELCOME_BOT_CLIENT_ID
    WELCOME_BOT_HASHTAG
    WELCOME_BOT_DRY_RUN
    """
    env_vars = {
        "WELCOME_BOT_API_BASE_URL": True,
        "WELCOME_BOT_USERNAME": True, 
        "WELCOME_BOT_PASSWORD": True, 
        "WELCOME_BOT_CLIENT_SECRET": True, 
        "WELCOME_BOT_CLIENT_ID": True, 
        "WELCOME_BOT_HASHTAG": True,
        "WELCOME_BOT_DRY_RUN": False,
        "WELCOME_BOT_BATCH_SIZE": False
    }

    output = {}
    for (key, required) in env_vars:
        if required and key not in environ:
            raise ValueError("Required environment variable %s not found", key)
        output[key.lstrip("WELCOME_BOT_").lower()] = environ[key]

    return output

# Global state sucks, use carefully
_client = None

def get_or_create_client(api_base_url, username, password, client_id, client_secret, logger):
    """
    Lazily initializes the Mastodon client. This is useful for avoiding the setup overhead each time the handler is called.
    """
    global _client
    if _client is None:
        logger.info("Attempting to authenticate with the API at \"%s\" using client id \"%s\"", api_base_url, client_id)
        logger.debug("Attempting to authenticate using client secret \"%s\"", client_secret)
        _client = Mastodon(
            api_base_url = api_base_url,
            client_id = client_id,
            client_secret = client_secret,
        )
        logger.info("Attempting to log in using username \"%s\"", username)
        logger.debug("Attempting to log in using password \"%s\"", password)
        access_token = _client.log_in(username = username, password = password, scopes = ["write:statuses"])
        logger.info("Successfully logged in")
        logger.debug("Received access token \"%s\"", access_token)
    return _client 

def get_with_default(key, data, default):
    """
    Tries to get a value in some data, but if it's not there calls the default function.
    
    It would be nice if dict().get had took a default function.
    """
    if key in data and data[key] is not None:
        return data[key]
    else:
        return default()

def set_log_level(level):
    """
    Attempts to set the log level to an appropriate value
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % level)
    logging.basicConfig(level=numeric_level)


def aws_lambda_handler(event, context):
    """
    This is the entry point for AWS Lambda. This is a single poll cycle. It's expected that this is run recursively as part of a AWS Step Function. 
    The results are the starting spot for the next iteration.
    """
    set_log_level(environ.get("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)
    env_vars = collect_env_vars(logger)
    
    logger.debug("Got env vars %s", env_vars)

    client = get_or_create_client(env_vars["api_base_url"], env_vars["username"], env_vars["password"], env_vars["client_id"], env_vars["client_secret"], logger)
    welcome_bot = WelcomeBot(client, logger, dry_run = (env_vars["dry_run"] == "TRUE"), batch_size = int(env_vars["batch_size"]))
    
    # If we don't know where we are, we'll start _after_ the most recent toot
    since_id = get_with_default("since_id", event, lambda: welcome_bot.get_most_recent_id(hashtag)) 

    latest_id = welcome_bot.retoot_intros(hashtag, since_id)

    return {
        "result": "success",
        "output": {
            "since_id": latest_id 
        }
    }


# This gets called if this file is being run directly via python welcomebot
# Executing it this way will simply poll stuff forever
if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--api-base-url")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret")
    parser.add_argument("--hashtag")
    parser.add_argument("--dry-run", type=bool, default=False)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--since-id", default=None)
    parser.add_argument("--log-level", default="DEBUG")
    args = parser.parse_args()
    set_log_level(args.log_level)
    logger = logging.getLogger(__name__)
    client = get_or_create_client(args.api_base_url, args.username, args.password, args.client_id, args.client_secret, logger)
    welcome_bot = WelcomeBot(client, logger, batch_size = args.batch_size, dry_run = args.dry_run)

    # If we don't know where we are, we'll start _after_ the most recent toot
    since_id = get_with_default("since_id", vars(args), lambda: welcome_bot.get_most_recent_id(args.hashtag))

    while True:
        since_id = welcome_bot.retoot_intros(args.hashtag, since_id)
        logger.debug("Sleeping for %s seconds", args.poll_interval)
        sleep(args.poll_interval)

