"""All signal lists and constant strings used for conversation flow detection."""

FOLLOWUP_FAILURE_SIGNALS = [
    "still not working",
    "didn't help",
    "no change",
    "problem persists",
    "issue persists",
    "not fixed",
    "didn't solve",
    "did not solve",
    "same issue",
    "nothing changed",
    "doesn't work",
    "does not work",
    "not resolved",
    "keeps happening",
    "again",
    "tried everything",
    "followed steps but",
    "all steps but",
    "no luck",
    "failed again",
]

ESCALATION_TRIGGERS = [
    "i don't know based on the knowledge base",
    "i'm not sure",
    "i cannot find",
    "i could not find",
    "not found in the",
    "no information",
    "unable to find",
    "doesn't appear to be covered",
    "does not appear to be covered",
    "may need to",
    "you might want to contact",
    "it's possible that",
    "i'm unable to",
    "i am unable to",
    "unclear",
    "not certain",
]

ESCALATION_SUFFIX = "\n\n⚠️ If not, please contact IT support if the issue persists."

TOOL_REQUEST_SIGNALS = [
    "lookup user",
    "find user",
    "check device",
    "device status",
    "create ticket",
    "create a ticket",
    "open ticket",
    "open a ticket",
    "raise ticket",
    "raise a ticket",
    "lookup ticket",
    "look up ticket",
    "look up a ticket",
    "ticket status",
    "ticket details",
    "check ticket",
    "escalate",
    "user",
    "username",
    "name",
    "get user",
    "get username",
    "get tickets",
    "ticket",
    "device",
    # "check my device",
    # "check device for",
]

TICKET_LOOKUP_SIGNALS = [
    "lookup ticket",
    "look up ticket",
    "lookup tickets",
    "look up tickets",
    "ticket status",
    "ticket details",
    "check ticket",
    "ticket info",
    "ticket information",
    "find ticket",
    "find tickets",
    "search ticket",
    "search tickets",
    "get ticket",
    "get tickets"
    # "show all my tickets",
    # "show tickets",
    # "show all tickets",
]

TICKET_REQUEST_SIGNALS = [
    "create ticket",
    "create a ticket",
    "open ticket",
    "open a ticket",
    "raise ticket",
    "raise a ticket",
    "escalate this",
    "escalate issue",
    "escalate",
    "ticket",
    "need ticket",
    "need to open ticket",
    "want to open ticket",
    "want to create ticket",
    "want to raise ticket",
    "want to raise a ticket"
]

TICKET_CONFIRMATION_SIGNALS = [
    "yes",
    "yes please",
    "please do",
    "go ahead",
    "do it",
    "proceed",
    "create one",
    "open one",
    "raise one",
    "sure",
    "okay",
    "ok",
    "yeah",
    "yep",
    "ya",
    "yes thanks",
    "yes thank you",
    "please create a ticket",
    "please open a ticket",
    "please raise a ticket",
    "please do create a ticket",
    "please do open a ticket",
    "please do raise a ticket",
]

END_CONVERSATION_SIGNALS = [
    "good bye",
    "bye",
    "goodbye",
    "see you",
    "talk to you later",
    "thanks, that's all",
    "that's all for now",
    "no, that's all",
    "nothing else",
    "no, nothing else",
    "all done",
    "all set",
    "that's it",
    "that's all",
    "thank you, that's all",
    "thank you, nothing else",
    "thank you, no, that's all",
    "thank you, that's all for now",
    "thanks, nothing else"
]

# ── Conversation prompt strings ──────────────────────────────────────────────

IDENTITY_LOOKUP_PROMPT = (
    "Thanks. Please provide either your username or your email so I can look up your account details."
)

LOOKUP_METHOD_PROMPT = (
    "Would you like to look up the user by username or by first and last name? "
    "Please reply with 'username' or 'name'."
)
LOOKUP_USERNAME_INPUT_PROMPT = "Please provide the username (for example, john.doe)."
LOOKUP_FIRST_NAME_PROMPT = "Please provide the first name."
LOOKUP_LAST_NAME_PROMPT = "Please provide the last name."
LOOKUP_DISAMBIGUATE_PROMPT = (
    "Multiple users found. Please enter the match number of the user you'd like to proceed with "
    "(for example, reply with '1' for Match 1)."
)
LOOKUP_NEXT_ACTION_PROMPT = (
    "What would you like to do next? Reply with 'device' to check device details "
    "or 'ticket' to create a support ticket."
)

KB_TICKET_IDENTITY_METHOD_PROMPT = (
    "To open a support ticket I'll need to identify you. "
    "Would you like to provide your username, email address, or first and last name? "
    "Please reply with 'username', 'email', or 'name'."
)
KB_TICKET_USERNAME_INPUT_PROMPT = "Please provide your username (for example, john.doe)."
KB_TICKET_EMAIL_INPUT_PROMPT = "Please provide your email address."
KB_TICKET_FIRST_NAME_PROMPT = "Please provide your first name."
KB_TICKET_LAST_NAME_PROMPT = "Please provide your last name."

CC_EMAIL_PROMPT = (
    "Would you like to add another email address to be CC'd on this ticket? "
    "Reply 'yes' or 'no'."
)
CC_EMAIL_INPUT_PROMPT = "Please provide the email address to add to CC."

TICKET_LOOKUP_NUMBER_PROMPT = (
    "Please provide the ticket number you'd like to look up (for example, 12345)."
)
TICKET_LOOKUP_METHOD_PROMPT = (
    "Would you like to look up a ticket by ticket number, by username, or by user first and last name? "
    "Reply with 'number', 'username', or 'name'."
)
TICKET_LOOKUP_USER_PROMPT = (
    "Please provide the first name of the user to retrieve tickets for."
)
TICKET_LOOKUP_USER_LAST_NAME_PROMPT = (
    "Please provide the last name of the user to retrieve tickets for."
)
TICKET_LOOKUP_USERNAME_PROMPT = (
    "Please provide the username (for example, john.doe) to retrieve tickets for."
)

# Long-input summarization threshold
LONG_INPUT_THRESHOLD = 200
INPUT_SUMMARY_CONFIRM_MARKER = "Does this accurately capture your request?"

HISTORY_LIMIT = 12
KNOWLEDGE_TOP_K = 10
