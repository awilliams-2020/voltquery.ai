#!/usr/bin/env python3
"""
Script to merge duplicate user accounts with the same email address.

This script:
1. Finds all users with duplicate email addresses
2. Keeps the account with the most activity (queries, better subscription)
3. Migrates queries from duplicate accounts to the primary account
4. Deletes duplicate accounts

Usage:
    python scripts/merge_duplicate_accounts.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.user import User
from app.models.query import Query
from app.models.subscription import Subscription
from collections import defaultdict


def find_duplicate_users(db: Session):
    """Find all users with duplicate email addresses."""
    # Get all users grouped by email
    users_by_email = defaultdict(list)
    users = db.scalars(select(User)).all()
    
    for user in users:
        users_by_email[user.email.lower()].append(user)
    
    # Filter to only emails with duplicates
    duplicates = {
        email: users 
        for email, users in users_by_email.items() 
        if len(users) > 1
    }
    
    return duplicates


def choose_primary_account(users: list[User], db: Session) -> tuple[User, list[User]]:
    """
    Choose the primary account to keep.
    
    Criteria (in order):
    1. Account with better subscription (higher query_limit)
    2. Account with more queries
    3. Older account (created_at)
    
    Returns: (primary_user, duplicate_users)
    """
    # Score each user
    scored_users = []
    
    for user in users:
        subscription = db.scalar(
            select(Subscription).where(Subscription.user_id == user.id)
        )
        query_count = db.scalar(
            select(func.count(Query.id)).where(Query.user_id == user.id)
        ) or 0
        
        score = {
            'user': user,
            'query_limit': subscription.query_limit if subscription else 0,
            'query_count': query_count,
            'created_at': user.created_at
        }
        scored_users.append(score)
    
    # Sort by: query_limit (desc), query_count (desc), created_at (asc)
    scored_users.sort(
        key=lambda x: (-x['query_limit'], -x['query_count'], x['created_at'])
    )
    
    primary = scored_users[0]['user']
    duplicates = [s['user'] for s in scored_users[1:]]
    
    return primary, duplicates


def merge_accounts(db: Session, primary: User, duplicate: User):
    """
    Merge a duplicate account into the primary account.
    
    - Migrates all queries from duplicate to primary
    - Deletes duplicate account (cascades to subscription)
    """
    print(f"  Merging account {duplicate.id} (clerk_id: {duplicate.clerk_id}) into {primary.id} (clerk_id: {primary.clerk_id})")
    
    # Migrate queries
    queries = db.scalars(
        select(Query).where(Query.user_id == duplicate.id)
    ).all()
    
    migrated_count = 0
    for query in queries:
        query.user_id = primary.id
        migrated_count += 1
    
    print(f"    Migrated {migrated_count} queries")
    
    # Delete duplicate account (subscription will be cascade deleted)
    db.delete(duplicate)
    db.commit()
    
    print(f"    Deleted duplicate account")


def main():
    """Main function to merge duplicate accounts."""
    db = SessionLocal()
    
    try:
        print("Finding duplicate user accounts...")
        duplicates = find_duplicate_users(db)
        
        if not duplicates:
            print("No duplicate accounts found!")
            return
        
        print(f"\nFound {len(duplicates)} email(s) with duplicate accounts:")
        for email, users in duplicates.items():
            print(f"  {email}: {len(users)} accounts")
        
        print("\nMerging duplicate accounts...")
        
        total_merged = 0
        for email, users in duplicates.items():
            print(f"\nProcessing email: {email}")
            primary, duplicate_users = choose_primary_account(users, db)
            
            print(f"  Keeping primary account: {primary.id} (clerk_id: {primary.clerk_id})")
            
            # Get subscription info for primary
            primary_sub = db.scalar(
                select(Subscription).where(Subscription.user_id == primary.id)
            )
            if primary_sub:
                print(f"    Subscription: {primary_sub.plan} plan, {primary_sub.query_limit} query limit")
            
            # Merge each duplicate
            for duplicate in duplicate_users:
                merge_accounts(db, primary, duplicate)
                total_merged += 1
        
        print(f"\n✅ Successfully merged {total_merged} duplicate account(s)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()



