class Player:
    def __init__(self, uid):
        self.uid = uid
        self.points = 0

    def addPoints(self, num):
        self.points += num

    def getPoints(self):
        return self.points