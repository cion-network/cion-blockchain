from typing import AsyncIterator, List, Tuple

import pytest

from chia.cmds.units import units
from chia.types.peer_info import PeerInfo
from tests.block_tools import create_block_tools_async
from chia.server.server import ChiaServer
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.util.ints import uint16
from chia.wallet.wallet_node import WalletNode
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import (
    self_hostname,
    setup_full_node,
    setup_full_system,
    test_constants,
    setup_simulators_and_wallets,
)
from tests.time_out_assert import time_out_assert
from tests.util.keyring import TempKeyring

test_constants_modified = test_constants.replace(
    **{
        "DIFFICULTY_STARTING": 2 ** 8,
        "DISCRIMINANT_SIZE_BITS": 1024,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "MAX_SUB_SLOT_BLOCKS": 50,
        "NUM_SPS_SUB_SLOT": 32,  # Must be a power of 2
        "EPOCH_BLOCKS": 280,
        "SUB_SLOT_ITERS_STARTING": 2 ** 20,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 5,
    }
)


class TestSimulation:
    @pytest.fixture(scope="function")
    async def extra_node(self):
        with TempKeyring() as keychain:
            b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=keychain)
            async for _ in setup_full_node(test_constants_modified, "blockchain_test_3.db", 21240, b_tools):
                yield _

    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(test_constants_modified):
            yield _

    @pytest.fixture(scope="function")
    async def one_wallet_node(
        self,
    ) -> AsyncIterator[Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]]]:
        async for _ in setup_simulators_and_wallets(simulator_count=1, wallet_count=1, dic={}):
            yield _

    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation, extra_node):
        node1, node2, _, _, _, _, _, _, _, server1 = simulation
        await server1.start_client(PeerInfo(self_hostname, uint16(21238)))
        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(1500, node_height_at_least, True, node2, 7)

        async def has_compact(node1, node2):
            peak_height_1 = node1.full_node.blockchain.get_peak_height()
            headers_1 = await node1.full_node.blockchain.get_header_blocks_in_range(0, peak_height_1)
            peak_height_2 = node2.full_node.blockchain.get_peak_height()
            headers_2 = await node2.full_node.blockchain.get_header_blocks_in_range(0, peak_height_2)
            # Commented to speed up.
            # cc_eos = [False, False]
            # icc_eos = [False, False]
            # cc_sp = [False, False]
            # cc_ip = [False, False]
            has_compact = [False, False]
            for index, headers in enumerate([headers_1, headers_2]):
                for header in headers.values():
                    for sub_slot in header.finished_sub_slots:
                        if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
                            # cc_eos[index] = True
                            has_compact[index] = True
                        if (
                            sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                            and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                        ):
                            # icc_eos[index] = True
                            has_compact[index] = True
                    if (
                        header.challenge_chain_sp_proof is not None
                        and header.challenge_chain_sp_proof.normalized_to_identity
                    ):
                        # cc_sp[index] = True
                        has_compact[index] = True
                    if header.challenge_chain_ip_proof.normalized_to_identity:
                        # cc_ip[index] = True
                        has_compact[index] = True

            # return (
            #     cc_eos == [True, True] and icc_eos == [True, True] and cc_sp == [True, True] and cc_ip == [True, True]
            # )
            return has_compact == [True, True]

        await time_out_assert(1500, has_compact, True, node1, node2)
        node3 = extra_node
        server3 = node3.full_node.server
        peak_height = max(node1.full_node.blockchain.get_peak_height(), node2.full_node.blockchain.get_peak_height())
        await server3.start_client(PeerInfo(self_hostname, uint16(21237)))
        await server3.start_client(PeerInfo(self_hostname, uint16(21238)))
        await time_out_assert(600, node_height_at_least, True, node3, peak_height)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
    async def test_simulation_process_blocks(
        self,
        count,
        one_wallet_node: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]],
    ):
        [[full_node_api], _] = one_wallet_node

        # Starting at the beginning.
        assert full_node_api.full_node.blockchain.get_peak_height() is None

        await full_node_api.process_blocks(count=count)

        # The requested number of blocks had been processed.
        expected_height = None if count == 0 else count
        assert full_node_api.full_node.blockchain.get_peak_height() == expected_height

    @pytest.mark.asyncio
    @pytest.mark.parametrize(argnames="count", argvalues=[0, 1, 2, 5, 10])
    async def test_simulation_farm_blocks(
        self,
        count,
        one_wallet_node: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]],
    ):
        [[full_node_api], [[wallet_node, wallet_server]]] = one_wallet_node

        await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

        # Avoiding an attribute error below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        # Starting at the beginning.
        assert full_node_api.full_node.blockchain.get_peak_height() is None

        rewards = await full_node_api.farm_blocks(count=count, wallet=wallet)

        # The requested number of blocks had been processed plus 1 to handle the final reward
        # transactions in the case of a non-zero count.
        expected_height = count
        if count > 0:
            expected_height += 1

        peak_height = full_node_api.full_node.blockchain.get_peak_height()
        if peak_height is None:
            peak_height = 0

        assert peak_height == expected_height

        # The expected rewards have been received and confirmed.
        unconfirmed_balance = await wallet.get_unconfirmed_balance()
        confirmed_balance = await wallet.get_confirmed_balance()
        assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        argnames=["amount", "coin_count"],
        argvalues=[
            [0, 0],
            [1, 2],
            [(2 * units["chia"]) - 1, 2],
            [2 * units["chia"], 2],
            [(2 * units["chia"]) + 1, 4],
            [3 * units["chia"], 4],
            [10 * units["chia"], 10],
        ],
    )
    async def test_simulation_farm_rewards(
        self,
        amount: int,
        coin_count: int,
        one_wallet_node: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]],
    ):
        [[full_node_api], [[wallet_node, wallet_server]]] = one_wallet_node

        await wallet_server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)

        # Avoiding an attribute error below.
        assert wallet_node.wallet_state_manager is not None

        wallet = wallet_node.wallet_state_manager.main_wallet

        rewards = await full_node_api.farm_rewards(amount=amount, wallet=wallet)

        # At least the requested amount was farmed.
        assert rewards >= amount

        # The rewards amount is both received and confirmed.
        unconfirmed_balance = await wallet.get_unconfirmed_balance()
        confirmed_balance = await wallet.get_confirmed_balance()
        assert [unconfirmed_balance, confirmed_balance] == [rewards, rewards]

        # The expected number of coins were received.
        # TODO: pick a better way to check coin count
        spendable_amount = await wallet.get_spendable_balance()
        all_coins = await wallet.select_coins(amount=spendable_amount)
        assert len(all_coins) == coin_count
