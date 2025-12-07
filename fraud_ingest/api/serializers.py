"""
Django REST Framework serializers for data validation and representation
of all primary models in the fraud detection system.

Includes serializers for:
1. User authentication (UserRegistrationSerializer).
2. Raw data ingestion (RawTransactionSerializer).
3. Derived feature data (UserProfileSerializer, EnrichedSerializer).
4. Model output (MLPredictionSerializer).
"""

from rest_framework import serializers
from .models import UserProfile, Enriched, MLPrediction, User, RawTransaction
from django.contrib.auth.password_validation import validate_password


class RawTransactionSerializer(serializers.ModelSerializer):
    type = serializers.IntegerField(source='transaction_type')

    class Meta:
        model = RawTransaction
        fields = [
            'transactionId',
            'step',
            'type',
            'amount',
            'nameOrig',
            'oldbalanceOrg',
            'newbalanceOrig',
            'nameDest',
            'oldbalanceDest',
            'newbalanceDest',
            'isFraud',
            'kyc_tier'
        ]

    def validate_transactionId(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("transactionId cannot be empty")
        return value

    def validate_step(self, value):
        if value < 0:
            raise serializers.ValidationError("step must be non-negative")
        return value

    def validate_type(self, value):
        if value not in [0, 1, 2, 3, 4]:
            raise serializers.ValidationError("type must be between 0 and 4")
        return value

    def validate_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("amount must be non-negative")
        return value

    def validate_nameOrig(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("nameOrig cannot be empty")
        return value

    def validate_nameDest(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("nameDest cannot be empty")
        return value

    def validate_isFraud(self, value):
        if value not in [0, 1]:
            raise serializers.ValidationError("isFraud must be 0 or 1")
        return value

    def validate_kyc_tier(self, value):
        if value not in [0, 1, 2, 3, 4]:
            raise serializers.ValidationError("kyc_tier must be 0, 1, 2, 3, 4")
        return value

    def validate(self, attrs):
        old_balance = attrs.get('oldbalanceOrg', 0)
        new_balance = attrs.get('newbalanceOrig', 0)

        if old_balance < 0 or new_balance < 0:
            raise serializers.ValidationError(
                "Balances cannot be negative"
            )

        return attrs


class UserProfileSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserProfile
        fields = '__all__'


class EnrichedSerializer(serializers.ModelSerializer):

    class Meta:
        model = Enriched
        fields = '__all__'


class MLPredictionSerializer(serializers.ModelSerializer):

    class Meta:
        model = MLPrediction
        fields = '__all__'


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        label="Confirm password"
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'fullname', 'password', 'password2')
        extra_kwargs = {
            'fullname': {'required': False}
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({
                "password": "Password fields didn't match."
                })

        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            fullname=validated_data.get('fullname', '')
        )

        return user
