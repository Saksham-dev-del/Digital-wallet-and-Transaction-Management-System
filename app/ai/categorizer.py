"""AI #1 - Smart expense categoriser.

A Multinomial Naive Bayes text classifier written from scratch (no ML library needed).
Features = words + character trigrams, so spelling mistakes ("swigy", "zomatto") and Hinglish
("chai nashta", "bijli bill") still work. It starts with a seed vocabulary of Indian student
spending and keeps learning whenever a user corrects a category (online learning).
"""
import math
import re
import threading
from collections import Counter

CATEGORIES = ["Food & Dining", "Groceries", "Transport", "Shopping", "Bills & Recharge", "Entertainment",
              "Health", "Education", "Rent & Housing", "Travel", "Friends & Family", "Other"]

SEED = {
    "Food & Dining": [
        "swiggy order", "swiggy dinner", "zomato lunch", "zomato order", "pizza hut", "dominos pizza", "chai nashta",
        "tea and samosa", "canteen lunch", "mess fees", "mess food", "restaurant bill", "cafe coffee day", "starbucks coffee",
        "burger king", "biryani", "lunch with friends", "dinner split", "momos", "maggi", "street food chaat", "ice cream",
        "bakery cake", "khana", "thali", "food", "breakfast", "snacks", "juice", "kfc", "mcdonalds", "chai", "coffee", "dinner",
        "lunch", "pizza", "burger", "dhaba", "tiffin", "eatsure", "swigy", "zomatto"],
    "Groceries": [
        "bigbasket groceries", "blinkit order", "zepto groceries", "kirana store", "sabzi vegetables", "dudh milk",
        "fruits and vegetables", "dmart", "grocery shopping", "atta rice dal", "supermarket", "grocery", "vegetables",
        "milk bread eggs", "instamart", "ration", "kiryana", "sabji", "fruit seller", "provision store"],
    "Transport": [
        "uber ride", "ola cab", "rapido bike", "auto rickshaw", "metro card recharge", "petrol pump", "fuel", "bus ticket",
        "e rickshaw", "parking fee", "fastag recharge", "taxi", "cab to station", "auto fare", "petrol", "diesel", "metro",
        "cab", "bike taxi", "ride to campus", "local train pass", "bus pass", "uber", "ola", "rapido", "toll"],
    "Shopping": [
        "amazon order", "flipkart purchase", "myntra clothes", "ajio order", "shoes", "tshirt", "electronics gadget",
        "headphones", "laptop bag", "meesho order", "nykaa", "mobile cover", "clothes", "jeans", "shirt", "online shopping",
        "amazon", "flipkart", "myntra", "keyboard mouse", "charger cable", "watch", "backpack", "sneakers", "decathlon"],
    "Bills & Recharge": [
        "jio recharge", "airtel postpaid", "vi recharge", "electricity bill", "bijli bill", "water bill",
        "wifi broadband bill", "gas cylinder", "dth recharge", "tata sky", "mobile recharge", "postpaid bill", "bsnl",
        "light bill", "recharge", "broadband", "internet bill", "phone bill", "airtel", "jio", "electricity", "cylinder refill",
        "d2h", "fiber plan"],
    "Entertainment": [
        "netflix subscription", "spotify premium", "hotstar", "prime video", "bookmyshow movie", "cinema ticket", "pvr",
        "gaming steam", "youtube premium", "concert tickets", "bgmi uc", "ps plus", "netflix", "spotify", "movie", "movie night",
        "gaming", "xbox game pass", "sonyliv", "zee5", "inox", "party entry", "club cover"],
    "Health": [
        "apollo pharmacy", "medicine", "dawai", "doctor consultation", "hospital", "lab test", "medplus", "gym membership",
        "dentist", "1mg", "pharmeasy", "eye checkup", "pharmacy", "clinic fees", "vitamins", "blood test", "gym", "yoga class",
        "medical store", "health checkup", "physio"],
    "Education": [
        "college fees", "tuition fee", "udemy course", "coursera", "books", "kitab", "stationery", "exam fee", "coaching",
        "photocopy xerox", "notes printout", "library fine", "byjus", "leetcode premium", "hackathon registration", "course fee",
        "semester fee", "certification exam", "textbook", "pen copy", "online course", "workshop fee", "lab manual", "project print"],
    "Rent & Housing": [
        "house rent", "hostel rent", "pg rent", "room rent", "hostel fees", "maintenance charges", "security deposit",
        "landlord", "society maintenance", "mess and hostel", "monthly rent", "flat rent", "rent", "broker fee", "hostel fee",
        "pg fees", "room deposit"],
    "Travel": [
        "irctc train ticket", "flight ticket", "makemytrip", "goibibo", "hotel booking", "oyo room", "redbus", "trip to goa",
        "holiday", "airport cab", "vacation", "tour package", "train ticket", "flight", "hotel", "hostel booking trip", "trek",
        "weekend trip", "indigo", "air india", "bus booking", "railway reservation", "tatkal"],
    "Friends & Family": [
        "pocket money", "to mom", "to dad", "birthday gift", "borrowed money returned", "paid back", "split", "shagun",
        "bhai", "didi", "friend", "chai pani", "udhaar", "gift to friend", "sent to family", "mummy", "papa", "returning money",
        "loan repay", "sharing bill", "party contribution", "gift", "rakhi", "birthday", "treat"],
}

_TOKEN = re.compile(r"[a-z0-9]+")


def features(text: str) -> list:
    out = []
    for word in _TOKEN.findall(text.lower()):
        if len(word) < 2:
            continue
        out.append("w:" + word)
        padded = f"^{word}$"
        out.extend("c:" + padded[i:i + 3] for i in range(len(padded) - 2))
    return out


class Categorizer:
    ALPHA = 0.5

    def __init__(self):
        self._lock = threading.RLock()
        self.counts = {c: Counter() for c in CATEGORIES}
        self.totals = Counter()
        self.vocab: set = set()
        self.seed_phrases = 0
        self.corrections = 0
        for cat, phrases in SEED.items():
            for p in phrases:
                self._add(p, cat, 1)
                self.seed_phrases += 1

    def _add(self, text: str, category: str, weight: int) -> None:
        with self._lock:
            for f in features(text):
                self.counts[category][f] += weight
                self.totals[category] += weight
                self.vocab.add(f)

    # ---------------------------------------------------------------- learning
    def learn(self, text: str, category: str, weight: int = 4) -> bool:
        """Online learning: a user's correction counts `weight` times more than a seed phrase."""
        if category not in self.counts or not text.strip():
            return False
        self._add(text, category, weight)
        self.corrections += 1
        return True

    def warm_start(self, rows) -> int:
        n = 0
        for text, category in rows:
            n += 1 if self.learn(text, category) else 0
        return n

    # ---------------------------------------------------------------- prediction
    def predict(self, text: str, top: int = 3) -> dict:
        with self._lock:
            known = [f for f in features(text) if f in self.vocab]
            if not known:
                return {"category": "Other", "confidence": 0.0, "top": []}
            V = len(self.vocab)
            loglik = {}
            for c in CATEGORIES[:-1]:                      # "Other" is the fallback, not a class we learn
                total, cnt = self.totals[c], self.counts[c]
                loglik[c] = sum(math.log((cnt.get(f, 0) + self.ALPHA) / (total + self.ALPHA * V)) for f in known)
        # Naive Bayes is over-confident with many correlated features -> temper by sqrt(n)
        temper = math.sqrt(len(known))
        scaled = {c: v / temper for c, v in loglik.items()}
        m = max(scaled.values())
        exp = {c: math.exp((v - m) * 2.2) for c, v in scaled.items()}
        z = sum(exp.values())
        probs = sorted(((c, e / z) for c, e in exp.items()), key=lambda x: -x[1])
        best, conf = probs[0]
        if conf < 0.35:
            best = "Other"
        return {"category": best, "confidence": round(conf, 3),
                "top": [{"category": c, "p": round(p, 3)} for c, p in probs[:top]]}

    def info(self) -> dict:
        return {"type": "Multinomial Naive Bayes (words + character trigrams)", "categories": len(CATEGORIES),
                "vocabulary": len(self.vocab), "seed_phrases": self.seed_phrases,
                "learned_from_user_corrections": self.corrections}
