import asyncio
import logging
import pprint
from datetime import datetime, timedelta
from typing import Callable, Optional
from typing import List, Dict

import schwab
from schwab.client import AsyncClient
from schwab.streaming import StreamClient

API_KEY = "XXXXXX"
CLIENT_SECRET = "XXXXXX"
CALLBACK_URL = "https://xxxxxx"


async def get_chains(client: AsyncClient, instruments: List[str]) -> Dict:
    chains = {}

    from_date = datetime.today().date()
    to_date = from_date + timedelta(days=3)

    for instrument in instruments:
        chain = await client.get_option_chain(
            instrument, from_date=from_date, to_date=to_date
        )
        if chain.status_code == 200:
            chains[instrument] = chain.json()

    return chains


def get_contracts_names(contracts: Dict) -> List[str]:
    names = []
    for instrument in contracts:
        names += [contract["symbol"] for contract in contracts[instrument]]

    return names


def get_contracts_from_chain(chain, days=1) -> List[str]:
    contracts = []
    for map_type in ["putExpDateMap", "callExpDateMap"]:
        counter = 0
        for idx, exp_date in enumerate(chain.get(map_type, {})):
            if counter == days:
                break

            days_to_expire = int(exp_date.split(":")[-1])
            if days_to_expire < 0:
                continue

            for strike in chain[map_type][exp_date]:
                contract = chain[map_type][exp_date][strike][0]
                contracts.append(contract)
            counter += 1

    sorted_array = sorted(contracts, key=lambda x: -x["openInterest"])
    return sorted_array


def get_contracts_from_chains(chains: Dict) -> Dict:
    contracts = {}
    for instrument in chains:
        contracts[instrument] = get_contracts_from_chain(chains[instrument], 2)

    return contracts


class OptionsDataStream:
    def __init__(
        self,
        instruments: List[str],
        process_context: Callable,
        api_key,
        client_secret,
        callback_url,
        token_path="./token.json",
        on_success: Optional[Callable] = None,
        queue_size: int = 0,
    ):
        """
        We're storing the configuration variables within the class for easy
        access later in the code!
        """
        logging.info("OptionsDataStream:: Initiating stream")

        self.api_key = api_key
        self.client_secret = client_secret
        self.callback_url = callback_url
        self.token_path = token_path

        self.account_id = None
        self.schwab_client = None
        self.stream_client = None
        self.instruments = instruments
        self.process_context = process_context
        self.on_success = on_success

        # Create a queue, so we can queue up work gathered from the client
        self.queue = asyncio.Queue(queue_size)

    async def initialize(self):
        """
        Create the clients and log in. Token should be previously generated using client_from_manual_flow()

        TODO: update to easy_client() when client_from_login_flow() works,
        or when easy_client() can redirect to client_from_manual_flow()
        """
        logging.info("OptionsDataStream:: preparing clients")

        self.schwab_client = schwab.auth.client_from_token_file(
            self.token_path, api_key=self.api_key, app_secret=self.client_secret
        )

        response = await self.schwab_client.get_account_numbers()

        if response.status_code != 200:
            raise Exception(response.status_code)

        account_info = response.json()

        self.account_id = int(account_info[0]["accountNumber"])

        self.stream_client = StreamClient(
            self.schwab_client, account_id=self.account_id
        )

        # The streaming client wants you to add a handler for every service type
        self.stream_client.add_level_one_option_handler(self.handle_level_one_option)

    async def stream(self):
        logging.info("OptionsDataStream:: logging in and collecting data")

        await self.stream_client.login()  # Log into the streaming service

        # TODO: QOS is currently not working as the command formatting has changed.
        #  Update & re-enable after docs are released
        # await self.stream_client.quality_of_service(StreamClient.QOSLevel.EXPRESS)

        chains = await get_chains(self.schwab_client, self.instruments)
        if len(chains) != len(self.instruments):
            raise Exception("Missing instruments")

        contracts = get_contracts_from_chains(chains)
        contracts_valid = {
            True if len(value) > 0 else False for key, value in contracts.items()
        }
        if contracts_valid != {True}:
            raise Exception("Contracts not valid")

        contracts = get_contracts_names(contracts)

        await self.stream_client.level_one_option_subs(contracts)

        # Initiate something after everything works (send news)
        if self.on_success:
            await self.on_success()

        # Kick off our handle_queue function as an independent coroutine
        asyncio.ensure_future(self.handle_queue())

        # Continuously handle inbound messages
        while True:
            try:
                await self.stream_client.handle_message()
            except:
                logging.exception("error occurred")

    async def handle_level_one_option(self, msg):
        """
        This is where we take msgs from the streaming client and put them on a
        queue for later consumption. We use a queue to prevent us from wasting
        resources processing old data, and falling behind.
        """
        # if the queue is full, make room
        if self.queue.full():  # This won't happen if the queue doesn't have a max size
            logging.warning(
                "Handler queue is full. Awaiting to make room... Some messages might be dropped"
            )
            await self.queue.get()
        await self.queue.put(msg)

    async def handle_queue(self):
        """
        Here we pull messages off the queue and process them.
        """
        while True:
            msg = await self.queue.get()
            await self.process_context(msg)


async def process_msg(msg: Dict):
    pprint.pprint(msg)


async def main():
    """
    Create and instantiate the consumer, and start the stream
    """
    data_stream = OptionsDataStream(
        instruments=["$SPX", "SPY"],
        process_context=process_msg,
        api_key=API_KEY,
        client_secret=CLIENT_SECRET,
        callback_url=CALLBACK_URL,
    )

    await data_stream.initialize()
    await data_stream.stream()


if __name__ == "__main__":
    asyncio.run(main())
