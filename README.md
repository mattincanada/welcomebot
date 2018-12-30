# welcomebot

This is a welcome bot for Mastodon written to be simple, cheap, and easy to maintain.

## Setup

### Prerequisites

In order to run this bot you'll need:
- Python 3.6.x
- A working C compiler
- libffi
- openssl
- virtualenv
- ???

### Development Environment

Create a virtualenv by running:

```
$ virtualenv venv
```

Then activate it by running:

```
$ source venv/bin/activate
```

### Authorization

This bot uses the Password Grant OAuth2 Flow. It's not the greatest, but we _assume that you aren't using your own account_.

In order to create a Mastodon application, from your bot account, visit https://<instance>/settings/applications

From that page create a new application and give it only the `write:statuses` scope.

Copy the client key (client id) and the client secret. The client secret should be kept secret.

The only other things you'll need for authorization is the username and password. These are the email and password that you would log into the bot user with.


### Local setup

You can run the bot locally via:

```
$ python welcomebot.py --api-base-url https://<instance> --username <login email> --password <password> --hashtag <into hashtag> --dry-run true --client-id <client id> --client-secret <client secret>
```

### AWS Lambda

TODO
