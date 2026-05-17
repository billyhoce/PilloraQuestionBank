#!/usr/bin/env python3
"""
Import topics and subtopics from a text file.

Format:
  1
  Topic Name
  Subtopic 1
  Subtopic 2
  2
  Another Topic
  Subtopic A
  Subtopic B

Usage:
  python scripts/import_topics.py <file_path> <subject_name> <stream_name>

Example:
  python scripts/import_topics.py topics.txt Math G1
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models.orm import Topic, Subtopic, Subject, Stream
from app.config import settings


def parse_topics_file(file_path: str) -> list[dict]:
    """Parse topics file and return list of topic dicts with subtopics."""
    topics = []

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = [line.rstrip('\n') for line in f.readlines()]

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Check if line is a topic number
        if line.isdigit():
            topic_number = int(line)
            i += 1

            # Next non-empty line is topic name
            while i < len(lines) and not lines[i].strip():
                i += 1

            if i >= len(lines):
                print(f"Warning: Topic {topic_number} has no name, skipping")
                break

            topic_name = lines[i].strip()
            i += 1

            # Collect subtopics until next topic number
            subtopics = []
            while i < len(lines):
                line = lines[i].strip()

                if not line:
                    i += 1
                    continue

                # Check if this is next topic number
                if line.isdigit():
                    break

                # This is a subtopic
                subtopics.append(line)
                i += 1

            topics.append({
                'number': topic_number,
                'name': topic_name,
                'subtopics': subtopics
            })
        else:
            i += 1

    return topics


def import_topics(file_path: str, subject_name: str, stream_name: str):
    """Import topics and subtopics into database."""

    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found")
        sys.exit(1)

    # Parse file
    topics_data = parse_topics_file(file_path)

    if not topics_data:
        print("No topics found in file")
        sys.exit(1)

    print(f"Parsed {len(topics_data)} topics from file")
    for topic in topics_data:
        print(f"  Topic {topic['number']}: {topic['name']} ({len(topic['subtopics'])} subtopics)")

    # Connect to database
    engine = create_engine(settings.database_url, echo=False)

    with Session(engine) as session:
        # Find subject and stream
        subject = session.query(Subject).filter(Subject.name == subject_name).first()
        if not subject:
            print(f"Error: Subject '{subject_name}' not found")
            sys.exit(1)

        stream = session.query(Stream).filter(Stream.name == stream_name).first()
        if not stream:
            print(f"Error: Stream '{stream_name}' not found")
            sys.exit(1)

        print(f"\nImporting to Subject: {subject.name} (id={subject.id}), Stream: {stream.name} (id={stream.id})")

        # Import topics
        for topic_data in topics_data:
            # Check if topic already exists
            existing = session.query(Topic).filter(
                Topic.subject_id == subject.id,
                Topic.stream_id == stream.id,
                Topic.name == topic_data['name']
            ).first()

            if existing:
                print(f"Topic '{topic_data['name']}' already exists (id={existing.id}), updating subtopics...")
                topic = existing
                # Remove old subtopics
                session.query(Subtopic).filter(Subtopic.topic_id == topic.id).delete()
            else:
                topic = Topic(
                    subject_id=subject.id,
                    stream_id=stream.id,
                    name=topic_data['name'],
                    topic_number=topic_data['number']
                )
                session.add(topic)
                print(f"Created topic '{topic_data['name']}' (number={topic_data['number']})")

            # Add subtopics
            for subtopic_name in topic_data['subtopics']:
                subtopic = Subtopic(
                    topic_id=topic.id,
                    name=subtopic_name
                )
                session.add(subtopic)
                print(f"  + Added subtopic: {subtopic_name}")

        # Commit all changes
        session.commit()
        print("\n✓ Import completed successfully!")


if __name__ == '__main__':
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)

    file_path = sys.argv[1]
    subject_name = sys.argv[2]
    stream_name = sys.argv[3]

    import_topics(file_path, subject_name, stream_name)
