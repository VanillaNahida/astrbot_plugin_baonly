from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .api import BaonlyClient
from .cards import DetailCardService, HelpCardService
from .events import EventCatalog
from .meta import RuntimeInfo
from .push import StreamNotifier
from .render import CardRenderer
from .screenshot import SiteScreenshotter
from .settings import Settings
from .subscriptions import ContactDirectory, SubscriptionStore
from .subscriptions.webui import SubscriptionWebApi


@dataclass
class PluginServices:
    settings: Settings
    runtime: RuntimeInfo
    catalog: EventCatalog
    detail_cards: DetailCardService
    help_cards: HelpCardService
    screenshots: SiteScreenshotter
    subscriptions: SubscriptionStore
    contacts: ContactDirectory
    notifier: StreamNotifier
    webui: SubscriptionWebApi

    @classmethod
    def build(cls, context: Any, config: Any) -> PluginServices:
        settings = Settings.from_config(config)
        runtime = RuntimeInfo.detect()
        catalog = EventCatalog(BaonlyClient(settings.token, settings.user_agent), settings.events_page_size)
        renderer = CardRenderer(settings)
        store = SubscriptionStore()
        contacts = ContactDirectory(context)
        return cls(
            settings=settings,
            runtime=runtime,
            catalog=catalog,
            detail_cards=DetailCardService(renderer, runtime),
            help_cards=HelpCardService(renderer, runtime),
            screenshots=SiteScreenshotter(settings, runtime),
            subscriptions=store,
            contacts=contacts,
            notifier=StreamNotifier(context, settings, catalog, store),
            webui=SubscriptionWebApi(store, contacts),
        )

    async def aclose(self) -> None:
        await self.notifier.stop()
        await self.catalog.client.aclose()
