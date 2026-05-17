import Player
import bisect


# Given UID and name from scanner app

class Database:
    Database = {}

    def newPlayer(UID, name):
        Database.append(UID, Player(UID, name))
    
    def findPlayer(UID, name=None):
        if UID not in Database:
            self.newPlayer(UID, name)
        else:
            return Database[UID]
        