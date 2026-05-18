import Player
from collections.abc import Sequence


class Database:
    players = {}

    @staticmethod
    def newPlayer(uid):
        # Create Player object and register in dict
        Database.players[uid] = Player.Player(uid)
    
    @staticmethod
    def findPlayer(uid):
        if uid not in Database.players:
            Database.newPlayer(uid)
        return Database.players[uid]


class PlayersView(Sequence):
    """A read-only live view of registered player UIDs."""
    def __len__(self):
        return len(Database.players)

    def __getitem__(self, index):
        return list(Database.players.keys())[index]

    def __iter__(self):
        return iter(Database.players.keys())

    def __contains__(self, item):
        return item in Database.players


# Module-level live view named `players`.
players = PlayersView()


def get_players():
    """Return a list of all registered player UIDs."""
    return list(Database.players.keys())
        