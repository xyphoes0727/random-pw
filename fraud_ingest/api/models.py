"""
Django ORM models for the fraud detection and data pipeline system.

This module defines models for:
1. Custom User authentication (User, UserManager).
2. User behavior aggregation (UserProfile).
3. Raw transaction data ingestion (RawTransaction).
4. Feature-enriched transaction data (Enriched).
5. Machine Learning fraud predictions (MLPrediction).
6. Model performance tracking (Metrics).
"""

from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from datetime import datetime


class UserManager(BaseUserManager):
    """
    Custom manager for the User model, providing methods for creating
    regular users and superusers.
    """
    def create_user(self, username, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model implementing AbstractBaseUser for custom authentication
    using 'username' as the unique identifier.
    """
    fullname = models.CharField(max_length=100, null=True, blank=True)
    username = models.CharField(
        max_length=50, unique=True, null=False, blank=False
    )
    password = models.CharField(max_length=128)
    email = models.EmailField(
        max_length=200, unique=True, null=False, blank=False
    )

    date_joined = models.DateTimeField(default=datetime.now)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    def __str__(self):
        return self.username


class UserProfile(models.Model):
    """
    Stores aggregated and calculated features about
    a user's transaction history.
    This is used for feature engineering in the fraud detection pipeline.
    The 'account' field serves as the primary key (PK).
    """
    account = models.CharField(max_length=255, primary_key=True)
    mean_amount = models.FloatField(null=True, blank=True)
    sum_amount_sq = models.FloatField(null=True, blank=True)
    max_amount_seen = models.FloatField(null=True, blank=True)
    min_amount_seen = models.FloatField(null=True, blank=True)
    txn_count = models.IntegerField(null=True, blank=True)
    latest_step = models.IntegerField(null=True, blank=True)
    variance = models.FloatField(null=True, blank=True)
    stddev_amount = models.FloatField(null=True, blank=True)
    time = models.BigIntegerField(null=True, blank=True)
    diff = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'user_profiles'

    def __str__(self):
        return self.account


class RawTransaction(models.Model):
    """
    Stores the initial, raw transaction data as ingested into the system
    (e.g., via Kafka).
    """
    transactionId = models.CharField(max_length=255, primary_key=True)
    step = models.IntegerField()
    transaction_type = models.IntegerField(db_column='type')
    amount = models.FloatField()
    nameOrig = models.CharField(max_length=255)
    oldbalanceOrg = models.FloatField()
    newbalanceOrig = models.FloatField()
    nameDest = models.CharField(max_length=255)
    oldbalanceDest = models.FloatField()
    newbalanceDest = models.FloatField()
    isFraud = models.IntegerField()
    kyc_tier = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'raw_transactions'
        indexes = [
            models.Index(fields=['nameOrig']),
            models.Index(fields=['step']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return self.transactionId


class Enriched(models.Model):
    """
    Stores transaction records after being enriched with calculated features
    from UserProfile, aggregate windowing, and graph features (e.g., pagerank).
    This dataset is typically used as input for ML models.
    """
    transactionId = models.CharField(max_length=255, primary_key=True)
    step = models.IntegerField(null=True, blank=True)
    transaction_type = models.IntegerField(
        db_column='type', null=True, blank=True)
    amount = models.FloatField(null=True, blank=True)
    nameOrig = models.CharField(max_length=255, null=True, blank=True)
    oldbalanceOrg = models.FloatField(null=True, blank=True)
    newbalanceOrig = models.FloatField(null=True, blank=True)
    nameDest = models.CharField(max_length=255, null=True, blank=True)
    oldbalanceDest = models.FloatField(null=True, blank=True)
    newbalanceDest = models.FloatField(null=True, blank=True)
    isFraud = models.IntegerField(null=True, blank=True)

    mean_amount = models.FloatField(null=True, blank=True)
    stddev_amount = models.FloatField(null=True, blank=True)
    max_amount_seen = models.FloatField(null=True, blank=True)
    min_amount_seen = models.FloatField(null=True, blank=True)
    user_txn_count = models.IntegerField(null=True, blank=True)

    txn_count_in_step = models.IntegerField(null=True, blank=True)
    total_amount_in_step = models.FloatField(null=True, blank=True)

    sender_out_degree = models.IntegerField(null=True, blank=True)
    sender_in_degree = models.IntegerField(null=True, blank=True)
    sender_fraud_ratio = models.FloatField(null=True, blank=True)
    pagerank = models.FloatField(null=True, blank=True)

    amount_to_profile_ratio = models.FloatField(null=True, blank=True)
    amount_to_balance_ratio = models.FloatField(null=True, blank=True)
    logamount = models.FloatField(null=True, blank=True)

    time = models.BigIntegerField(null=True, blank=True)
    diff = models.IntegerField(null=True, blank=True)
    origMoreSent = models.FloatField(null=True, blank=True)
    destMoreRec = models.FloatField(null=True, blank=True)
    origMoreSentFlag = models.IntegerField(null=True, blank=True)
    destMoreRecFlag = models.IntegerField(null=True, blank=True)

    trust_score = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'enriched'
        indexes = [
            models.Index(fields=['nameOrig']),
            models.Index(fields=['step']),
            models.Index(fields=['isFraud']),
        ]

    def __str__(self):
        return self.transactionId


class MLPrediction(models.Model):
    """
    Stores the output and metadata from the Machine Learning
    fraud prediction model.
    It has a One-to-One relationship with the Enriched transaction record.
    """
    transaction = models.OneToOneField(
        Enriched,
        on_delete=models.CASCADE,
        primary_key=True,
        db_column='transactionId'
    )

    amount = models.FloatField(null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    fraud_probability = models.FloatField(null=True, blank=True)
    isFraud = models.IntegerField(null=True, blank=True)
    label = models.CharField(max_length=255, null=True, blank=True)
    time = models.BigIntegerField(null=True, blank=True)
    diff = models.IntegerField(null=True, blank=True)
    is_verified_human = models.BooleanField(null=True, blank=True)
    is_verified_system = models.BooleanField(null=True, blank=True)
    verification_time = models.BigIntegerField(null=True, blank=True)
    ground_truth = models.IntegerField(null=True, blank=True, default=None)
    is_counted_metrics = models.BooleanField(default=False)

    class Meta:
        db_table = 'ml_prediction'

    def __str__(self):
        return f"Prediction for {self.transaction_id}"


class Metrics(models.Model):
    """
    Stores calculated performance metrics (e.g., precision, recall, F1-score)
    for the ML fraud detection model at specific time intervals.
    """
    fp = models.PositiveIntegerField(null=True, blank=True)
    tp = models.PositiveIntegerField(null=True, blank=True)
    tn = models.PositiveIntegerField(null=True, blank=True)
    fn = models.PositiveIntegerField(null=True, blank=True)
    precision = models.FloatField(null=True, blank=True)
    recall = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    tpr = models.FloatField(null=True, blank=True)
    fpr = models.FloatField(null=True, blank=True)
    f1_score = models.FloatField(null=True, blank=True)
    watermark_ms = models.BigIntegerField(null=True, blank=True)
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'metrics'
        ordering = ['-calculated_at']
        # Speeds up latest metrics lookups.
        indexes = [models.Index(fields=['calculated_at'])]

    def __str__(self):
        return f"Metrics at time {self.id}"
