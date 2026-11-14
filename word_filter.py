from word_filter import profanity

profanity.load_censor_words()

def contains_profanity(*texts):
    return any(t and profanity.contains_profanity(t) for t in texts)