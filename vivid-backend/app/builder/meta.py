"""The prompt builder: a one-line idea becomes a full brief before anyone
asks a question.

Users write "an ecommerce site for my sneakers". That is enough for a
person who has built shops before and nothing like enough for a builder.
The first plan turn runs the idea through a meta-prompt that writes the
brief a good product designer would: what it is, who it is for, the pages
and flows, the data, what content and pictures it needs, look and feel,
and the assumptions worth confirming. The brief is shown to the user,
stored on the project, and is what the questions and the spec build on.
"""
import logging

from app.builder import routing
from app.builder.loop import ModelStep

log = logging.getLogger("vivid.builder.meta")

#: Ideas shorter than this are the ones a brief helps most; longer input is
#: still expanded, but the user's own words are kept whole.
SHORT_WORDS = 60

META_PROMPT = """You turn a short idea for a web app into a complete brief, the way a senior product \
designer would before a kickoff. The person may not be technical and may have written one \
line. Do not ask questions here; make the best assumptions and mark them.

Write the brief in markdown with exactly these headings:

## What it is
One paragraph: the business or purpose, the one thing the app must do well, the country and \
city if implied (default Nigeria, Lagos, naira).

## Who it is for
The customer in one or two lines, and the owner or admin if there is one. What each wants \
to get done in under a minute.

## Pages and flows
Every page a first version needs, one line each with what is on it; then the two or three \
key flows step by step (for a shop: find, add to cart, order; for a booking site: pick, \
choose a time, confirm).

## Data
Each thing the app stores with its fields, and where it lives (the browser only, or an \
account system with a database).

## Content and pictures
What copy and images the app needs to look real: product photos, a logo or wordmark, hero \
image, opening hours, address, phone, prices. Say which the owner should supply and which \
can be generated or written.

## Look and feel
One line on tone, one on colour direction, one on type, with a reason tied to the audience. \
Two contrasting alternatives in one line each.

## Assumptions to confirm
Three to six things you decided that the owner might want differently, each as a short \
question with your default.

Be concrete and specific to this idea; no generic filler, no marketing tone, under 450 words."""


#: The same brief for an iOS and Android app: screens, not pages.
MOBILE_META_PROMPT = (META_PROMPT
                      .replace("a short idea for a web app", "a short idea for a mobile app "
                               "(iOS and Android, built with Expo)")
                      .replace("## Pages and flows\nEvery page a first version needs",
                               "## Screens and flows\nThe tabs (two to five) and every screen "
                               "a first version needs")
                      .replace("(the browser only, or", "(on the phone only, or")
                      .replace("hero image", "app icon, splash screen"))


class Expansion:
    """Runs the meta-prompt as a streamed step; `text` holds the brief."""

    def __init__(self, user_text: str, images: list[str] | None = None,
                 mobile: bool = False) -> None:
        self.user_text, self.images = user_text, images
        self.mobile = mobile
        self.text = ""
        self.usage = None

    async def run(self):
        endpoint = routing.endpoint_for(routing.PLAN)
        content = self.user_text
        if self.images:
            content = [{"type": "text", "text": self.user_text}] + [
                {"type": "image_url", "image_url": {"url": u}} for u in self.images[:4]]
        step = ModelStep([{"role": "system",
                           "content": MOBILE_META_PROMPT if self.mobile else META_PROMPT},
                          {"role": "user", "content": content}], [], endpoint)
        async for part in step.run():
            yield part
        if step.failed is not None:
            log.warning("brief expansion failed: %s", step.failed)
            return
        self.text, self.usage = step.text, step.usage


def needs_brief(history: list[dict], user_text: str) -> bool:
    """Only the first message of a project; the rest are answers."""
    return not history and bool(user_text.strip())
