import unittest

from backend.app.pubmed import _parse_pubmed_xml

SAMPLE = """
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal>
          <Title>Example Journal</Title>
          <JournalIssue>
            <PubDate><Year>2024</Year></PubDate>
          </JournalIssue>
        </Journal>
        <ArticleTitle>Example title</ArticleTitle>
        <Abstract>
          <AbstractText>An abstract.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <Initials>J</Initials>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Review</PublicationType>
          <PublicationType>Review</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


class PubMedTypesTest(unittest.TestCase):
    def test_publication_types_reach_meta(self):
        articles = _parse_pubmed_xml(SAMPLE)
        self.assertEqual(len(articles), 1)
        meta = articles[0].to_meta()
        self.assertEqual(meta["pmid"], "12345678")
        self.assertEqual(meta["pub_types"], ["Journal Article", "Review"])


if __name__ == "__main__":
    unittest.main()
