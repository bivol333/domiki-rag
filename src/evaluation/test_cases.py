"""Hand-written evaluation test cases for Greek construction law retrieval."""
from src.evaluation.models import TestCase

TEST_CASES: list[TestCase] = [
    TestCase(
        query="διαδικασία υπαγωγής αυθαιρέτου",
        expected_articles=["Άρθρο 99", "Άρθρο 100", "Άρθρο 96"],
        expected_law="Ν. 4495/2017",
        notes="Κεντρικές διατάξεις τακτοποίησης αυθαιρέτων — δικαιολογητικά, πρόστιμα, κατηγορίες",
    ),
    TestCase(
        query="πρόστιμο αυθαίρετης κατασκευής",
        expected_articles=["Άρθρο 100", "Άρθρο 101"],
        expected_law="Ν. 4495/2017",
        notes="Πρόστιμα αυθαίρετων κατασκευών — υπολογισμός και κλιμάκωση",
    ),
    TestCase(
        query="αυθαίρετο σε παραδοσιακό οικισμό",
        expected_articles=["Άρθρο 116"],
        expected_law="Ν. 4495/2017",
        notes="Ειδικές διατάξεις για αυθαίρετα εντός παραδοσιακών οικισμών",
    ),
    TestCase(
        query="αυθαίρετα σε δάσος",
        expected_articles=["Άρθρο 89", "Άρθρο 90", "Άρθρο 116"],
        expected_law=None,
        notes="Αυθαίρετα σε δασικές εκτάσεις — ειδικές απαγορεύσεις",
    ),
    TestCase(
        query="Άρθρο 96",
        expected_articles=["Άρθρο 96"],
        expected_law="Ν. 4495/2017",
        notes="Ακριβής αναφορά άρθρου — ο article filter πρέπει να το φέρει στην κορυφή",
    ),
    TestCase(
        query="κατηγορίες αυθαιρέτων κατασκευών",
        expected_articles=["Άρθρο 96", "Άρθρο 97"],
        expected_law="Ν. 4495/2017",
        notes="Ταξινόμηση αυθαιρέτων σε κατηγορίες για τακτοποίηση",
    ),
    TestCase(
        query="δικαιολογητικά υπαγωγής αυθαιρέτων",
        expected_articles=["Άρθρο 99"],
        expected_law="Ν. 4495/2017",
        notes="Απαιτούμενα έγγραφα για αίτηση τακτοποίησης",
    ),
    TestCase(
        query="εξαιρέσεις από κατεδάφιση αυθαιρέτου",
        expected_articles=["Άρθρο 103", "Άρθρο 116"],
        expected_law=None,
        notes="Περιπτώσεις που εξαιρούνται από υποχρεωτική κατεδάφιση",
    ),
    TestCase(
        query="μεταβίβαση ακινήτου με αυθαίρετο",
        expected_articles=["Άρθρο 82", "Άρθρο 83"],
        expected_law="Ν. 4495/2017",
        notes="Νομικές προϋποθέσεις για μεταβίβαση ακινήτου με αυθαίρετες κατασκευές",
    ),
    TestCase(
        query="αυθαίρετα σε αιγιαλό παραλία",
        expected_articles=["Άρθρο 89", "Άρθρο 90"],
        expected_law=None,
        notes="Αυθαίρετα σε ζώνη αιγιαλού — ειδικό καθεστώς",
    ),
    TestCase(
        query="ηλεκτροδότηση αυθαιρέτου κτιρίου",
        expected_articles=["Άρθρο 85", "Άρθρο 86"],
        expected_law=None,
        notes="Όροι σύνδεσης αυθαιρέτων με δίκτυα κοινής ωφέλειας",
    ),
    TestCase(
        query="αυθαίρετο σε ρέμα υδατορέμα",
        expected_articles=["Άρθρο 89"],
        expected_law=None,
        notes="Αυθαίρετα εντός ορίων ρεμάτων",
    ),
    TestCase(
        query="ειδική εισφορά τακτοποίηση αυθαιρέτου",
        expected_articles=["Άρθρο 100", "Άρθρο 101", "Άρθρο 102"],
        expected_law="Ν. 4495/2017",
        notes="Υπολογισμός ειδικής εισφοράς/προστίμου για τακτοποίηση",
    ),
    TestCase(
        query="αυθαίρετα πριν από 1983",
        expected_articles=["Άρθρο 96", "Άρθρο 113"],
        expected_law=None,
        notes="Προγενέστερα αυθαίρετα — παλαιό καθεστώς νομιμοποίησης",
    ),
    TestCase(
        query="παράνομη κατασκευή εντός σχεδίου πόλεως",
        expected_articles=["Άρθρο 96", "Άρθρο 97", "Άρθρο 100"],
        expected_law="Ν. 4495/2017",
        notes="Αυθαίρετα εντός εγκεκριμένου ρυμοτομικού σχεδίου",
    ),
]
