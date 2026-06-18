"""seed reference data

Revision ID: e7a4d5f9b2c8
Revises: eb12b366e454
Create Date: 2026-05-08 02:31:10.628945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a4d5f9b2c8"
down_revision: Union[str, None] = "eb12b366e454"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lightweight table definitions for op.bulk_insert. We deliberately do NOT
# import the ORM here: migrations must be insulated from future model changes,
# so we redeclare only the columns this migration touches.

school_level_table = sa.table(
    "school_level",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

subject_table = sa.table(
    "subject",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

stream_table = sa.table(
    "stream",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("school_level_id", sa.Integer),
)

level_table = sa.table(
    "level",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("school_level_id", sa.Integer),
)

exam_type_table = sa.table(
    "exam_type",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

user_table = sa.table(
    "app_user",
    sa.column("id", sa.Integer),
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("role", sa.String),
)

topic_table = sa.table(
    "topic",
    sa.column("id", sa.Integer),
    sa.column("subject_id", sa.Integer),
    sa.column("stream_id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("topic_number", sa.Integer),
)

subtopic_table = sa.table(
    "subtopic",
    sa.column("id", sa.Integer),
    sa.column("topic_id", sa.Integer),
    sa.column("name", sa.String),
)


SCHOOL_LEVELS: list[dict] = [
    {"name": "Primary"},
    {"name": "Secondary"},
]

SUBJECTS: list[dict] = [
    {"name": "E Math"},
    {"name": "A Math"},
    {"name": "Science"},
]

# The "school_level" key on each stream/level is resolved to school_level_id
# in upgrade() after SCHOOL_LEVELS is inserted.
STREAMS: list[dict] = [
    {"name": "Foundation", "school_level": "Primary"},
    {"name": "Standard", "school_level": "Primary"},
    {"name": "G1", "school_level": "Secondary"},
    {"name": "G2", "school_level": "Secondary"},
    {"name": "G3", "school_level": "Secondary"},
]

LEVELS: list[dict] = [
    {"name": "1", "sort_order": 1, "school_level": "Primary"},
    {"name": "2", "sort_order": 2, "school_level": "Primary"},
    {"name": "3", "sort_order": 3, "school_level": "Primary"},
    {"name": "4", "sort_order": 4, "school_level": "Primary"},
    {"name": "5", "sort_order": 5, "school_level": "Primary"},
    {"name": "6", "sort_order": 6, "school_level": "Primary"},
    {"name": "1", "sort_order": 7, "school_level": "Secondary"},
    {"name": "2", "sort_order": 8, "school_level": "Secondary"},
    {"name": "3", "sort_order": 9, "school_level": "Secondary"},
    {"name": "4", "sort_order": 10, "school_level": "Secondary"},
]

EXAM_TYPES: list[dict] = [
    {"name": "WA1"},
    {"name": "WA2"},
    {"name": "WA3"},
    {"name": "End-of-Year"},
    {"name": "Prelim"},
    {"name": "PSLE"},
    {"name": "O-Level"},
]

# Initial admin user
USERS: list[dict] = [
    {
        "email": "admin@pillora.com",
        "password_hash": "$2b$12$xonr9H5ielxtIe3B1LKY6euSnfrUHTIkgFFz.bEZLUvM2kC6AOvgu",
        "role": "admin",
    },
]


# Topics seeded under (E Math, G3). Each topic owns a list of subtopic names.
TOPICS_SUBJECT = "E Math"
TOPICS_STREAM = "G3"

TOPICS: list[dict] = [
    {
        "number": 1,
        "name": "Primes, HCF, LCM",
        "subtopics": [
            "Able to Prime factorise",
            "Find HCF, LCM by prime factorisation",
            "Find perfect square/cube/square root/cube root by prime factorisation",
        ],
    },
    {
        "number": 2,
        "name": "Numbers Basics",
        "subtopics": [
            "Negative numbers, integers, rational numbers, real numbers, and their four operations",
            "Perform calculations with calculator",
            "Represent and order numbers on the number line",
            "Approximate and estimate (including rounding off numbers to a required number of decimal places or significant figures and estimating the results of computation)",
        ],
    },
    {
        "number": 3,
        "name": "Standard form",
        "subtopics": [
            "Use of standard form A × 10n, where n is an integer, and 1 ⩽ A < 10",
        ],
    },
    {
        "number": 4,
        "name": "Percentage",
        "subtopics": [
            "Express one quantity as a percentage of another/ compare two quantities by percentage",
            "increasing/decreasing",
        ],
    },
    {
        "number": 5,
        "name": "Ratio and Map Scales",
        "subtopics": [
            "Ratio - rational numbers and writing simplest form",
            "Able to form Distance and area map scales",
            "Able to calculate the actual distance/area given map and vice versa",
        ],
    },
    {
        "number": 6,
        "name": "Rate and Speed",
        "subtopics": [
            "Average rate and average Speed",
            "conversion of units (e.g. km/h to m/s)",
        ],
    },
    {
        "number": 7,
        "name": "Number Patterns",
        "subtopics": [
            "Able to form the general term expression",
            "Explain why a term is not part of the pattern",
        ],
    },
    {
        "number": 8,
        "name": "Sets",
        "subtopics": [
            "Set symbols/notations",
            "Draw venn diagrams from scratch",
            "Shade venn diagrams given the set language",
            "Write the sets given the venn diagram",
        ],
    },
    {
        "number": 9,
        "name": "Matrices",
        "subtopics": [
            "Display information in the form of a matrix of any order",
            "Interpret the data in a given matrix (write in words)",
            "Find product of a scalar quantity and a matrix",
            "Able to calculate the sum and difference of two matrices",
            "Able to calculate the product of two matrices",
        ],
    },
    {
        "number": 10,
        "name": "Algebra (Expand, Factorise, Solve)",
        "subtopics": [
            "Evaluate algebraic expressions and formulas (sub in numbers correctly)",
            "Expand and Simplify (special identities, fractional expressions)",
            "Able to multiply and divide algebraic fractions",
            "Factorisation (2,3,4 terms)",
            "Complete the square + know how to find turning point coordinates",
            "Make subject",
            "Solve quadratic equations in one unknown by factorisation, use of quadratic formula, completing the square, graphical methods",
            "Solve fractional equations that can be reduced to quadratic equations",
            "Forming equations to solve problems",
        ],
    },
    {
        "number": 11,
        "name": "Indices",
        "subtopics": [
            "Law of indices",
            "Positive, negative, zero and fractional indices",
            "Solving equations involving indices",
        ],
    },
    {
        "number": 12,
        "name": "Simultaneous equations",
        "subtopics": [
            "Solve by Substitution method",
            "Solve by Elimination method",
            "Solve by Graphical method",
        ],
    },
    {
        "number": 13,
        "name": "Inequalities",
        "subtopics": [
            "Linear Inequalities (solving and representing on number line)",
            "Simultaneous ineqalities (solving and representing on number line)",
        ],
    },
    {
        "number": 14,
        "name": "Direct/ Inverse Proportions",
        "subtopics": [
            "Proving/Showing two variables are in direct/inverse proportions",
            "Forming equation for direct/inverse proportion",
            "Finding percentage change",
            "3 variables",
        ],
    },
    {
        "number": 15,
        "name": "Graph Plotting",
        "subtopics": [
            "Basics (able to draw axis, find coordinates given x or y)",
            "Able to plot linear lines (y=mx+c)",
            "Able to draw quadratic and any other functions (curves)",
            "Able to draw tangent and estimate the gradient of the curve",
            "Able to solve equations using graph (need to manipulate the equation)",
        ],
    },
    {
        "number": 16,
        "name": "Graph Sketching",
        "subtopics": [
            "Understand the quadratic functions and their properties: positive or negative coefficient of x^2, maximum and minimum points, symmetry",
            "Sketch quadratic functions",
            "Sketch power functions where n = −2, −1, 0, 1, 2, 3",
            "Graphs of exponential functions where a is a positive integer",
        ],
    },
    {
        "number": 17,
        "name": "Basic Angles and Polygons",
        "subtopics": [
            "Right, acute, obtuse and reflex angles",
            "Vertically opposite angles, angles on a straight line and angles at a point",
            "Angles formed by two parallel lines and a transversal: corresponding angles, alternate angles, interior angles",
            "Properties of triangle and quadrilaterals",
            "Name all polygons (up to 10 sides)",
            "Finding interior and exterior angles of polygons (regular and irregular)",
        ],
    },
    {
        "number": 18,
        "name": "Circles",
        "subtopics": [
            "Properties of circles",
        ],
    },
    {
        "number": 19,
        "name": "Construction",
        "subtopics": [
            "Construct Triangle/Quadrilaterals",
            "Perpendicular Bisector/ Angle Bisector and their properties",
        ],
    },
    {
        "number": 20,
        "name": "Pythagoras' Theorem and Trigonometry",
        "subtopics": [
            "Pythagoras' Theorem",
            "Determine if a traingle is right-angled (Converse of Pythagoras)",
            "Basics (Use trigonometric ratios (sine, cosine and tangent) of acute angles to calculate unknown sides and angles in right-angled triangles)",
            "Extend sine and cosine to obtuse angles",
            "Use the formula for the area of a triangle",
            "Use sine rule and cosine rule for any triangle",
            "Solve problems in two and three dimensions including those involving angles of elevation and depression and bearings",
        ],
    },
    {
        "number": 21,
        "name": "Congruence and Similarity",
        "subtopics": [
            "Properties of similar triangles and polygons: corresponding angles are equal, corresponding sides are proportional",
            "Understand Enlargement and reduction of a plane figure",
            "scale drawwings (drawing same shape with lengths changed by the same ratio)",
            "Determine whether two triangles are congruent or similar using Congruence/Similarity Tests",
            "Ratio of similar figures/solids (area, volume)",
        ],
    },
    {
        "number": 22,
        "name": "Mensuration",
        "subtopics": [
            "Solving problems involving area and perimeter (plane figures: parallelogram, trapezium etc)",
            "Solving problems involving volume and surface area of cube, cuboid, prism, cylinder, pyramid, cone and sphere",
            "Arc length, sector area and area of a segment of a circle (using degrees and radians to solve)",
            "Conversion of all units (cm2 and m2, cm3 and m3, km/h and m/s, degree and radians)",
        ],
    },
    {
        "number": 23,
        "name": "Coordinate Geometry",
        "subtopics": [
            "Find the gradient of a straight line given the coordinates of two points on it",
            "Find the length of a line segment given the coordinates of its end points",
            "Interpret and find the equation of a straight line graph in the form y=mx+c",
            "Using coordinates to solve problems (e.g. knowing when to sub in x or y coordinate)",
            "Able to find shortest distance from a point to a line (usually involving area of triangle)",
            "Finding specific coordinates of parallelogram/rhombus based on their properties (opposite lengths are equal)",
        ],
    },
    {
        "number": 24,
        "name": "Vectors",
        "subtopics": [
            "Know when and how to use which notations (directed line segment, column vector or bolded letter)",
            "represent a vector using a line with an arrow to show its size and direction on a diagram",
            "Finding magnitude of a vector",
            "Understanding zero vectors, equal vectors, negative vectors and when two vectors are parallel",
            "Addition of vectors (triangle law and parallelogram law)",
            "Subtraction of vectors (addition of negative vectors and triangle law of vector subtraction)",
            "Able to multiply of a vector by a scalar",
            "Able to express a vector in terms of two other vectors",
            "Understanding position vectors",
            "Translation of a point by a vector",
            "Solving geometric problems involving the use of vectors (including using similarity concept)",
        ],
    },
    {
        "number": 25,
        "name": "Probability",
        "subtopics": [
            "Probability of single events (including listing all the possible outcomes in a simple chance situation to calculate the probability)",
            "Probability of simple combined events using Possibility Diagram",
            "Probability of simple combined events using Tree Diagram",
            "Add and multiply of probabilities (mutually exclusive events and independent events)",
        ],
    },
    {
        "number": 26,
        "name": "Statistics",
        "subtopics": [
            "Analyse and interpret tables, bar graphs, pictograms, line graphs, pie charts, dot diagrams, histograms with equal class intervals, stem-and-leaf diagrams, cumulative frequency diagrams, box-and-whisker plots",
            "Purpose and use, advantages and disadvantages of the different forms of statistical representations",
            "Explain why a given statistical diagram leads to misinterpretation of data",
            "Mean, mode and median as measures of central tendency for a set of data",
            "Purposes and use of mean, mode and median",
            "Calculate of the mean for grouped data",
            "Quartiles and percentiles",
            "Range, interquartile range and standard deviation as measures of spread for a set of data",
            "Calculate of the standard deviation for a set of data (grouped and ungrouped)",
            "Use the mean and standard deviation to compare two sets of data",
        ],
    },
    {
        "number": 27,
        "name": "Graph",
        "subtopics": [
            "Distance-Time",
            "Speed-Time",
        ],
    },
    {
        "number": 28,
        "name": "Finance",
        "subtopics": [
            "Compound Interest",
            "Hire/Purchase/ Simple interest",
            "Profit/Loss",
            "GST/Discounts",
            "Exchange rate",
            "Taxation",
            "Utilities/bills",
            "CPF",
            "Insurance",
            "Loans (Car, House)",
        ],
    },
    {
        "number": 29,
        "name": "Other Applications in Real World Context (RWC)",
        "subtopics": [
            "Solve problems based on real-world contexts in everyday life including travel plans, transport schedules, sports and games, recipes, etc.",
            "Solve problems in real-world contexts (including floor plans, surveying, navigation, etc.) using geometry",
        ],
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    if SCHOOL_LEVELS:
        op.bulk_insert(school_level_table, SCHOOL_LEVELS)

    school_level_ids = {
        row.name: row.id
        for row in bind.execute(sa.text("SELECT id, name FROM school_level"))
    }

    if SUBJECTS:
        op.bulk_insert(subject_table, SUBJECTS)
    if STREAMS:
        op.bulk_insert(
            stream_table,
            [
                {
                    "name": s["name"],
                    "school_level_id": school_level_ids[s["school_level"]],
                }
                for s in STREAMS
            ],
        )
    if LEVELS:
        op.bulk_insert(
            level_table,
            [
                {
                    "name": l["name"],
                    "sort_order": l["sort_order"],
                    "school_level_id": school_level_ids[l["school_level"]],
                }
                for l in LEVELS
            ],
        )
    if EXAM_TYPES:
        op.bulk_insert(exam_type_table, EXAM_TYPES)
    if USERS:
        op.bulk_insert(user_table, USERS)

    if TOPICS:
        subject_id = bind.execute(
            sa.text("SELECT id FROM subject WHERE name = :name"),
            {"name": TOPICS_SUBJECT},
        ).scalar_one()
        stream_id = bind.execute(
            sa.text("SELECT id FROM stream WHERE name = :name"),
            {"name": TOPICS_STREAM},
        ).scalar_one()

        op.bulk_insert(
            topic_table,
            [
                {
                    "subject_id": subject_id,
                    "stream_id": stream_id,
                    "name": t["name"],
                    "topic_number": t["number"],
                }
                for t in TOPICS
            ],
        )

        topic_ids = {
            row.name: row.id
            for row in bind.execute(
                sa.text(
                    "SELECT id, name FROM topic "
                    "WHERE subject_id = :subject_id AND stream_id = :stream_id"
                ),
                {"subject_id": subject_id, "stream_id": stream_id},
            )
        }

        subtopic_rows = [
            {"topic_id": topic_ids[t["name"]], "name": sub}
            for t in TOPICS
            for sub in t["subtopics"]
        ]
        if subtopic_rows:
            op.bulk_insert(subtopic_table, subtopic_rows)


def downgrade() -> None:
    bind = op.get_bind()

    if TOPICS:
        subject_row = bind.execute(
            sa.text("SELECT id FROM subject WHERE name = :name"),
            {"name": TOPICS_SUBJECT},
        ).first()
        stream_row = bind.execute(
            sa.text("SELECT id FROM stream WHERE name = :name"),
            {"name": TOPICS_STREAM},
        ).first()
        if subject_row and stream_row:
            # Subtopic rows cascade-delete with their parent topic.
            bind.execute(
                sa.text(
                    "DELETE FROM topic WHERE subject_id = :subject_id AND stream_id = :stream_id"
                ),
                {"subject_id": subject_row[0], "stream_id": stream_row[0]},
            )

    if USERS:
        emails = [u["email"] for u in USERS]
        bind.execute(
            sa.text("DELETE FROM app_user WHERE email = ANY(:emails)"),
            {"emails": emails},
        )
    if EXAM_TYPES:
        names = [e["name"] for e in EXAM_TYPES]
        bind.execute(
            sa.text("DELETE FROM exam_type WHERE name = ANY(:names)"),
            {"names": names},
        )
    if LEVELS:
        names = [l["name"] for l in LEVELS]
        bind.execute(
            sa.text("DELETE FROM level WHERE name = ANY(:names)"),
            {"names": names},
        )
    if STREAMS:
        names = [s["name"] for s in STREAMS]
        bind.execute(
            sa.text("DELETE FROM stream WHERE name = ANY(:names)"),
            {"names": names},
        )
    if SUBJECTS:
        names = [s["name"] for s in SUBJECTS]
        bind.execute(
            sa.text("DELETE FROM subject WHERE name = ANY(:names)"),
            {"names": names},
        )
    if SCHOOL_LEVELS:
        names = [sl["name"] for sl in SCHOOL_LEVELS]
        bind.execute(
            sa.text("DELETE FROM school_level WHERE name = ANY(:names)"),
            {"names": names},
        )
