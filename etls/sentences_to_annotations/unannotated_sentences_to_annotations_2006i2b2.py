import asyncio
import sys
import json
from etl.utils.dfutils import LakeDB
from utils.constants import DataConstants
from models.model import Sentence, Annotations, AnnotatedSentence, UserInfo2006i2b2
from utils.prompt import i2b2_2006_prompt
from etls.DSETL import DSETL
from typing import List
from common.utils.log import ConfigureLogging
from pydantic.json import pydantic_encoder
from loguru import logger
import os
from scripts.post_processing_of_tagged_sentences import (
    convert_human_readable_to_machine_readable_annotations,
    get_human_readable_annotations_2006i2b2,
)
import tqdm


class UnannotatedSnetencesTagging2006i2b2(DSETL[Sentence, AnnotatedSentence]):
    
    # Default options for the output directory
    DEFAULT_OPTIONS = {
        "out-dir": DataConstants.TAGGED_SENTENCES_MACHINE_DIR,
        "inp-dir": DataConstants.PROCESSED_SENTENCES_DIR,
    }

    def __init__(
        self,
        cli_tokens=None,
        options=None,
    ):
        # Initialize with default options and create necessary directories
        super().__init__(cli_tokens, options, self.DEFAULT_OPTIONS)
        self.root = self.options["root"]
        self.inp_dir = self.options["inp-dir"].format(root_dir=self.root)      
        self.inp_file_name = self.options["inp-file"]
        self.inp_file_path = self.inp_dir + "/" + self.inp_file_name
        self.out_dir = self.options["out-dir"].format(root_dir=self.root)
        self.out_file_name = self.options["out-file"].split(".")[0]
        self.out_db = LakeDB(self.out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self.sentence_tgging = None

    def set_algo(self, algo):
        self.sentence_tgging = algo

    async def extract(self) -> List[Sentence]:
        # step1: Read ndjson file from inp_db
        cs = self._read_ndjson_file_and_return_sentences(self.inp_file_path)
        logger.success(f"Reading Done...  from file {self.inp_file_path}")

        # step2: for all clinical notes make a List[ClinicalNote]
        return cs

    async def transform(self, data: List[Sentence]) -> List[AnnotatedSentence]:
        # Transform clinical notes to sentences
        ts = self._transform_sentences_to_tagged_sentences(data)
        logger.success(f"Sentences Tagging Done...  from file {self.inp_file_path}")
        return ts

    async def load(self, data: List[AnnotatedSentence]):
        # dump in outfile.ndjson format
        file_saved = self._write_tagged_sentences(data, self.out_file_name)
        logger.success(f"Loaded {len(data)} to file {file_saved}")
        return

    def _write_tagged_sentences(
        self, sentences: List[AnnotatedSentence], file_name: str, _type="ndjson"
    ) -> None:
        if _type != "ndjson":
            raise ValueError("Only 'ndjson' type is supported")
        with open(f"{self.out_db.db}/{file_name}.{_type}", "w") as f:
            for sentence in tqdm.tqdm(sentences):
                f.write(json.dumps(sentence, default=pydantic_encoder) + "\n")
        return f"{self.out_db.db}/{file_name}.{_type}"

    def _transform_sentences_to_tagged_sentences(
        self, sentences: List[Sentence]
    ) -> List[AnnotatedSentence]:
        annotated_snetences = []
        for sentence in tqdm.tqdm(sentences):
            # Tagging sentence with model and converting annotations
            userinfo = self.sentence_tgging.tagging_sentence(sentence.text, i2b2_2006_prompt, UserInfo2006i2b2)
            annotations = get_human_readable_annotations_2006i2b2(
                sentence=sentence.text, response_obj=userinfo
            )
            annotations = convert_human_readable_to_machine_readable_annotations(
                sentence=sentence.text, tags=annotations
            )
            annotated_snetences.append(
                AnnotatedSentence(
                    text=sentence.text,
                    sentence_id_in_note=sentence.sentence_id_in_note,
                    major_section=sentence.major_section,
                    associated_note_id=sentence.associated_note_id,
                    note_type=sentence.note_type,
                    date=sentence.date,
                    patient_id=sentence.patient_id,
                    metadata=sentence.metadata,
                    annotations=Annotations(
                        annotation_source="GPT", annotations=annotations
                    ),
                )
            )
            file_saved = self._write_tagged_sentences(
                annotated_snetences, self.out_file_name
            )
            # logger.success(f"Loaded {len(annotated_snetences)} to file {file_saved}")
        return annotated_snetences

    def _read_ndjson_file_and_return_sentences(self, file_path: str) -> List[Sentence]:
        # Reading sentences from ndjson file
        sentences = []
        with open(file_path, "r") as f:
            for line in tqdm.tqdm(f, desc="Processing lines"):
                sentence = Sentence.model_validate_json(line)
                sentences.append(sentence)
        return sentences


if __name__ == "__main__":
    # Run the ETL process for the first type
    ConfigureLogging()
    etl1 = UnannotatedSnetencesTagging2006i2b2(cli_tokens=sys.argv[1:])
    asyncio.run(etl1.run())
