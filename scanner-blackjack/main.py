import Player
import random



PlayerUID = Player.UID
PlayerName = Player.name
PlayerPoints = Player.points

BlackjackThreshold = 21

print("Hey", PlayerName + ", welcome to Scanner Blackjack!")

score = 0
failCase = False

while not failCase:
    Barcode = input("Scan your barcode: ")
    number = random.choice(Barcode)
    score += number

    print("You got a", number +".","You're total score is:", score)

    if score > BlackjackThreshold:
        failCase = True

    choice = input("Would you like to keep going? [Y]")

    if choice.lower == ("y" or "yes"):
        pass
    elif choice.lower == ("n" or "no"):
        break

if failCase:
    print("Your score exceeds the limit of", BlackjackThreshold + ".")
    print("You will lose the equivalent number of points from your account.")
    print("Points lost:", score)
    score *= -1

Player.addPoints(score)

print("Your final score is:", score)
print("Points won from this game have been added to your account.")
print("Account Balance:", PlayerPoints)