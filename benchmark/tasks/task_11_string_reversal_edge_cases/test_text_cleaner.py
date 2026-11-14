from text_cleaner import reverse_words

def test_reverse_words_standard():
    assert reverse_words("the sky is blue") == "blue is sky the"

def test_reverse_words_multiple_spaces():
    assert reverse_words("  hello   world  ") == "world hello"

def test_reverse_words_empty():
    assert reverse_words("") == ""
